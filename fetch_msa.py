"""Recover the MSA using the ColabFold-compatible service route."""
import io
import json
import tarfile
from pathlib import Path

import requests
import yaml

root = Path(__file__).resolve().parent
job_id = "Zhhmhvm1bw82t40MZlYLQe_HioNi1sNA5AT1Hg"
response = requests.get(
    f"https://api.colabfold.com/result/download/{job_id}",
    headers={"User-Agent": "colabfold/1.5.5"}, timeout=120,
)
response.raise_for_status()
msa_dir = root / "msa"
msa_dir.mkdir(exist_ok=True)
(msa_dir / "colabfold_result.tar.gz").write_bytes(response.content)
parts = []
with tarfile.open(fileobj=io.BytesIO(response.content)) as archive:
    for name in ["uniref.a3m", "bfd.mgnify30.metaeuk30.smag30.a3m"]:
        member = archive.extractfile(name)
        text = member.read().decode().replace("\x00", "")
        (msa_dir / name).write_text(text, encoding="utf-8")
        parts.append(text.rstrip() + "\n")
msa = "".join(parts)
sequence = "".join((root / "protein.fasta").read_text().splitlines()[1:])
assert msa.splitlines()[1] == sequence, "MSA query sequence mismatch"
msa_path = msa_dir / "protein.a3m"
msa_path.write_text(msa, encoding="utf-8")
data = yaml.safe_load((root / "protein.yaml").read_text(encoding="utf-8-sig"))
data["sequences"][0]["protein"]["msa"] = str(msa_path)
(root / "protein.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
metadata = {"source": "https://api.colabfold.com", "job_id": job_id,
            "query_length": len(sequence), "a3m_entries": sum(l.startswith(">") for l in msa.splitlines()),
            "note": "Boltz User-Agent download route returned 404; ColabFold-compatible route succeeded."}
(msa_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
print(json.dumps(metadata, indent=2))
