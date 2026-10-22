"""Validate full-length models, export PDB copies, and summarize confidence."""
import csv
import json
import shutil
import sys
from pathlib import Path

import gemmi
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
pred = ROOT / "results" / "boltz_results_protein" / "predictions" / "protein"
sequence = "".join((ROOT / "protein.fasta").read_text().splitlines()[1:])
rows = []
for cif in sorted(pred.glob("protein_model_*.cif")):
    name = cif.stem
    structure = gemmi.read_structure(str(cif))
    chain = structure[0]["A"]
    residues = [r for r in chain if r.find_atom("CA", "*")]
    actual = "".join(gemmi.find_tabulated_residue(r.name).one_letter_code for r in residues)
    if actual != sequence:
        raise ValueError(f"Sequence mismatch in {name}: {len(actual)} residues")
    coords = np.array([[a.pos.x, a.pos.y, a.pos.z] for r in residues for a in r])
    if not np.isfinite(coords).all():
        raise ValueError(f"Non-finite coordinates in {name}")
    structure.write_pdb(str(cif.with_suffix(".pdb")))
    confidence = json.loads((pred / f"confidence_{name}.json").read_text())
    rows.append({"model": name, "residues": len(residues), **{
        k: confidence.get(k) for k in ["confidence_score", "ptm", "complex_plddt"]
    }})
if len(rows) != 5:
    raise ValueError(f"Expected 5 validated models, got {len(rows)}")
rows.sort(key=lambda r: r["confidence_score"], reverse=True)
with (ROOT / "model_confidence.csv").open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
best = rows[0]["model"]
for extension in ["cif", "pdb"]:
    shutil.copy2(pred / f"{best}.{extension}", ROOT / f"best_model.{extension}")
with np.load(pred / f"plddt_{best}.npz") as data:
    plddt = data["plddt"].reshape(-1)
if len(plddt) != len(sequence):
    raise ValueError("Unexpected pLDDT length")
if plddt.max() <= 1.0:
    plddt = plddt * 100
with (ROOT / "residue_confidence.csv").open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["residue", "amino_acid", "plddt_0_100"])
    writer.writerows((i, aa, round(float(p), 2)) for i, (aa, p) in enumerate(zip(sequence, plddt), 1))
info = json.loads((ROOT / "run_info.json").read_text())
report = [
    "# Boltz-2 구조 예측 결과", "",
    f"사용자가 제공한 서열 381 aa를 단일 사슬 A로 예측했습니다. 5개 모델 모두 입력 서열과 좌표 유효성을 확인했습니다.",
    f"최고 신뢰도 모델: `{best}` → `best_model.cif`, `best_model.pdb`.", "",
    "| 모델 | confidence score | pTM | 평균 pLDDT (0–100) |",
    "|---|---:|---:|---:|",
]
for row in rows:
    report.append(f"| {row['model']} | {row['confidence_score']:.4f} | {row['ptm']:.4f} | {row['complex_plddt'] * 100:.2f} |")
report += ["", f"최고 모델에서 pLDDT < 50인 잔기: {int((plddt < 50).sum())}/{len(plddt)}.",
           f"최고 모델에서 pLDDT ≥ 70인 잔기: {int((plddt >= 70).sum())}/{len(plddt)}.", "",
           "pLDDT가 낮은 부위의 모양이나 PAE가 높은 영역 사이의 상대 배치를 확정 구조로 해석하지 마세요. 단일 사슬이며 금속·리간드·다량체 조건을 지정하지 않았습니다.", "",
           f"GPU: {info['gpu']}; 최대 PyTorch 할당 메모리 {info['peak_gpu_allocated_gib']:.2f} GiB, 예약 메모리 {info['peak_gpu_reserved_gib']:.2f} GiB.",
           f"성공한 GPU 예측 실행 소요 시간: {info['elapsed_seconds']/60:.1f}분 (최초 설치·모델 다운로드·MSA 복구 시간 제외).",
           "PDB의 B-factor 필드는 실험적 온도 인자가 아니라 모델 신뢰도입니다.", "",
           "설정과 재실행 방법: README.md. 잔기별 점수: residue_confidence.csv. 전체 PAE: 원본 predictions 폴더의 NPZ."]
(ROOT / "RESULTS.md").write_text("\n".join(report) + "\n", encoding="utf-8")
print("\n".join(report))
