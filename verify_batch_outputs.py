"""Integration check for the real two-chain demo and the desktop UI."""
import json
import sys
import time
from pathlib import Path

import gemmi
import numpy as np

ROOT = Path(__file__).resolve().parent
result = ROOT / "batch_examples" / "result"
metadata = json.loads((result / "evaluation" / "complex_demo.json").read_text(encoding="utf-8"))
reference = gemmi.read_structure(str(result / "aligned" / "complex_demo_0.pdb"))
reference_ca = np.array([[r["CA"][0].pos.x, r["CA"][0].pos.y, r["CA"][0].pos.z] for r in reference[0]["A"]])

for row in metadata["models"]:
    original = gemmi.read_structure(str(result / row["model"]))
    aligned = gemmi.read_structure(str(result / "aligned" / row["model"]))
    assert [len(original[0][c]) for c in ["A", "B"]] == [21, 30]
    assert [len(aligned[0][c]) for c in ["A", "B"]] == [21, 30]
    def points(st):
        return {(c.name, r.seqid.num, r.seqid.icode, a.name, a.altloc):
                [a.pos.x, a.pos.y, a.pos.z] for c in st[0] for r in c for a in r}
    original_atoms, aligned_atoms = points(original), points(aligned)
    assert original_atoms.keys() == aligned_atoms.keys()
    keys = sorted(original_atoms)
    before = np.array([original_atoms[k] for k in keys])
    after = np.array([aligned_atoms[k] for k in keys])
    # All atoms in all chains must undergo one rigid transformation.
    centered_before = before - before.mean(axis=0)
    centered_after = after - after.mean(axis=0)
    u, _, vt = np.linalg.svd(centered_before.T @ centered_after)
    rotation = u @ vt
    assert np.linalg.det(rotation) > 0.99
    assert np.max(np.abs(centered_before @ rotation - centered_after)) < 0.003
    ca = np.array([[r["CA"][0].pos.x, r["CA"][0].pos.y, r["CA"][0].pos.z] for r in aligned[0]["A"]])
    actual_rmsd = float(np.sqrt(np.mean(np.sum((ca - reference_ca) ** 2, axis=1))))
    assert abs(actual_rmsd - row["chain_A_RMSD_A"]) < 0.003
print("PASS: 5 two-chain PDBs; whole-complex rigid transformations; independent RMSD calculation", flush=True)

if "--ui" in sys.argv:
    from boltz_batch_gui import App
    app = App(ROOT / "batch_examples")
    app.update()
    app.select_file()
    app.update()
    assert len(app.files.get_children()) == 1
    assert len(app.scores.get_children()) == 5
    assert app.original_image is not None
    assert app.preview_photo is not None
    app.start()  # Cached run, verifies subprocess event stream and no repeat GPU inference.
    deadline = time.monotonic() + 40
    while app.process and time.monotonic() < deadline:
        app.update()
        time.sleep(0.05)
    assert app.process is None, "GUI batch did not finish"
    assert "재사용 1" in app.overall.get(), app.overall.get()
    assert len(app.scores.get_children()) == 5
    app.close()
    print("PASS: Tk two-column UI, image preview, score table, live events and cached batch completion", flush=True)
