"""FASTA validation, bounded ColabFold MSA requests and result validation."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import string
import tarfile
import time
from pathlib import Path

CHAIN_IDS = string.ascii_uppercase + string.ascii_lowercase + string.digits
AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWYX")
SETTINGS = {"model": "boltz2", "boltz": "2.2.1", "recycles": 3,
            "steps": 200, "samples": 5, "parallel": 1, "seed": 42,
            "msa": "colabfold-env-pairgreedy-v1"}


def read_seq(path: Path) -> list[dict]:
    """One FASTA record per chain; reject ambiguous/malformed input early."""
    records = []
    header = None
    chunks = []

    def finish():
        if header is None:
            return
        sequence = "".join(chunks).upper()
        if not sequence:
            raise ValueError(f"빈 FASTA 항목: {header}")
        invalid = sorted(set(sequence) - AMINO_ACIDS)
        if invalid:
            raise ValueError(f"{header}: 지원하지 않는 아미노산 문자 {''.join(invalid)!r}")
        if len(records) >= len(CHAIN_IDS):
            raise ValueError("PDB 형식의 단일 문자 chain ID 제한: 파일당 최대 62 chains")
        records.append({"id": CHAIN_IDS[len(records)], "header": header, "sequence": sequence})

    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith(">"):
            finish()
            header = line[1:].strip()
            if not header:
                raise ValueError(f"{line_no}행: FASTA 제목이 비어 있습니다.")
            chunks = []
        else:
            if header is None:
                raise ValueError(f"{line_no}행: 첫 서열 앞에 >제목이 필요합니다.")
            chunks.append("".join(line.split()))
    finish()
    if not records:
        raise ValueError("FASTA 서열이 없습니다.")
    return records


def fingerprint(records):
    return hashlib.sha256(json.dumps({"chains": records, "settings": SETTINGS},
                                     sort_keys=True).encode()).hexdigest()


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def split_a3m(text: str, count: int) -> list[list[str]]:
    groups = {101 + i: [] for i in range(count)}
    for block in text.split("\x00"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if not lines[0].startswith(">"):
            raise ValueError("잘못된 MSA block")
        key = int(lines[0][1:])
        if key not in groups:
            raise ValueError(f"예상하지 못한 MSA query ID: {key}")
        current = []
        for line in lines:
            if line.startswith(">"):
                if current:
                    groups[key].append("".join(current))
                    current = []
            else:
                current.append(line)
        if current:
            groups[key].append("".join(current))
    return [groups[101 + i] for i in range(count)]


def msa_request(sequences: list[str], paired: bool, directory: Path, log):
    import requests

    mode = "pairgreedy-env" if paired else "env"
    archive_path = directory / f"{mode}.tar.gz"
    if not archive_path.exists():
        session = requests.Session()
        session.headers["User-Agent"] = "colabfold/1.5.5"
        base = "https://api.colabfold.com"
        deadline = time.monotonic() + 1800

        def request(method, endpoint, **kwargs):
            for attempt in range(5):
                if time.monotonic() >= deadline:
                    raise TimeoutError("MSA 대기 제한(30분) 초과")
                try:
                    response = session.request(method, base + endpoint, timeout=(10, 120), **kwargs)
                    response.raise_for_status()
                    return response
                except requests.RequestException as exc:
                    if attempt == 4:
                        raise
                    log(f"MSA 연결 재시도 {attempt + 1}/5: {exc}")
                    time.sleep(5 * (attempt + 1))

        query = "".join(f">{101+i}\n{seq}\n" for i, seq in enumerate(sequences))
        endpoint = "/ticket/pair" if paired else "/ticket/msa"
        while True:
            result = request("POST", endpoint, data={"q": query, "mode": mode}).json()
            if result.get("status") not in {"UNKNOWN", "RATELIMIT"}:
                break
            log(f"MSA {mode}: {result['status']}; 10초 후 재시도")
            time.sleep(10)
        job = result.get("id")
        while result.get("status") in {"UNKNOWN", "RUNNING", "PENDING"}:
            if not job:
                raise ValueError(f"MSA 작업 ID 없음: {result}")
            log(f"MSA {mode}: {result['status']}")
            time.sleep(10)
            result = request("GET", f"/ticket/{job}").json()
        if result.get("status") != "COMPLETE" or not job:
            raise RuntimeError(f"MSA 서버 실패: {result}")
        log(f"MSA {mode}: 결과 다운로드")
        content = request("GET", f"/result/download/{job}").content
        # Validate before persisting. Never cache an HTML/JSON error as an archive.
        with tarfile.open(fileobj=io.BytesIO(content)) as archive:
            expected = "pair.a3m" if paired else "uniref.a3m"
            archive.getmember(expected)
        temporary = archive_path.with_suffix(".part")
        temporary.write_bytes(content)
        temporary.replace(archive_path)
    names = ["pair.a3m"] if paired else ["uniref.a3m", "bfd.mgnify30.metaeuk30.smag30.a3m"]
    combined = [[] for _ in sequences]
    with tarfile.open(archive_path) as archive:
        # Read only known members, without filesystem extraction.
        for name in names:
            member = archive.extractfile(name)
            if member is None:
                raise ValueError(f"MSA archive missing {name}")
            groups = split_a3m(member.read().decode("utf-8"), len(sequences))
            for i, group in enumerate(groups):
                combined[i].extend(group)
    for query, rows in zip(sequences, combined):
        if not rows or rows[0].replace("-", "").upper() != query:
            raise ValueError("MSA 첫 서열이 입력 서열과 다릅니다.")
        for row in rows:
            if len("".join(c for c in row if not c.islower())) != len(query):
                raise ValueError("MSA 정렬 길이가 query 길이와 다릅니다.")
    return combined


def prepare_input(records, work: Path, shared_msa: Path, log):
    import yaml

    unique = list(dict.fromkeys(r["sequence"] for r in records))
    cache_key = hashlib.sha256(json.dumps(unique).encode()).hexdigest()
    msa_dir = shared_msa / cache_key
    msa_dir.mkdir(parents=True, exist_ok=True)
    paths = [msa_dir / f"entity_{i}.csv" for i in range(len(unique))]
    if not all(path.exists() for path in paths):
        paired = msa_request(unique, True, msa_dir, log) if len(unique) > 1 else [[]]
        unpaired = msa_request(unique, False, msa_dir, log)
        for i, path in enumerate(paths):
            paired_rows = paired[i][:8192]
            keyed = [(j, s) for j, s in enumerate(paired_rows) if s.replace("-", "")]
            other = unpaired[i][1:] if keyed else unpaired[i]
            keyed += [(-1, s) for s in other[:16384 - len(keyed)]]
            temp = path.with_suffix(".tmp")
            with temp.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["key", "sequence"])
                writer.writerows(keyed)
            temp.replace(path)
            log(f"MSA entity {i}: {len(keyed)} rows (paired {len(paired_rows)})")
    else:
        log("동일 서열의 저장된 MSA 재사용")
    entities = []
    for i, sequence in enumerate(unique):
        ids = [r["id"] for r in records if r["sequence"] == sequence]
        entities.append({"protein": {"id": ids, "sequence": sequence, "msa": str(paths[i].resolve())}})
    output = work / "target.yaml"
    output.write_text(yaml.safe_dump({"version": 1, "sequences": entities}, sort_keys=False), encoding="utf-8")
    return output


def collect_models(prediction_dir: Path, records, stage: Path, stem: str):
    import gemmi
    import numpy as np

    models = list(prediction_dir.glob("*_model_*.cif"))
    if len(models) != 5:
        raise RuntimeError(f"5개 CIF가 필요합니다. 발견: {len(models)} (Boltz 로그를 확인하세요)")
    ranked = []
    for path in models:
        conf = json.loads((path.parent / f"confidence_{path.stem}.json").read_text())
        for key in ["confidence_score", "ptm", "complex_plddt"]:
            if not isinstance(conf.get(key), (float, int)) or not np.isfinite(conf[key]):
                raise ValueError(f"유효하지 않은 신뢰도: {path.name}, {key}")
        ranked.append((conf["confidence_score"], path, conf))
    ranked.sort(key=lambda item: (-item[0], item[1].name))
    rows = []
    stage.mkdir(parents=True, exist_ok=True)
    expected = {r["id"]: r["sequence"] for r in records}
    for rank, (_, path, conf) in enumerate(ranked):
        structure = gemmi.read_structure(str(path))
        if len(structure) != 1 or {c.name for c in structure[0]} != set(expected):
            raise ValueError(f"Chain 구성이 입력과 다릅니다: {path.name}")
        count = 0
        for chain in structure[0]:
            residues = [r for r in chain if r.find_atom("CA", "*")]
            actual = "".join(gemmi.find_tabulated_residue(r.name).one_letter_code.upper() for r in residues)
            if actual != expected[chain.name]:
                raise ValueError(f"서열 불일치: {path.name}, chain {chain.name}")
            count += sum(len(r) for r in residues)
            if not all(np.isfinite([a.pos.x, a.pos.y, a.pos.z]).all() for r in chain for a in r):
                raise ValueError(f"잘못된 좌표: {path.name}")
        if count > 99999 or any(len(s) > 9999 for s in expected.values()):
            raise ValueError("PDB 원자/잔기 번호 한계를 초과했습니다. 원본 CIF는 작업 폴더에 보존됩니다.")
        filename = f"{stem}_{rank}.pdb"
        structure.write_pdb(str(stage / filename))
        # Validate the actual PDB roundtrip, including chain identity.
        pdb = gemmi.read_structure(str(stage / filename))
        for chain_id, sequence in expected.items():
            if len([r for r in pdb[0][chain_id] if r.find_atom('CA', '*')]) != len(sequence):
                raise ValueError("PDB 변환 후 잔기 수 불일치")
        rows.append({"model": filename, "source": path.name, "confidence_score": conf["confidence_score"],
                     "pTM": conf["ptm"], "ipTM": conf.get("iptm") if len(records) > 1 else None,
                     "mean_pLDDT": 100 * conf["complex_plddt"], "chains": len(records),
                     "residues": sum(map(len, expected.values())), "confidence": conf})
    return rows
