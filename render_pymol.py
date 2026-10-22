"""Run via pymol -cq; config comes from BOLTZ_RENDER_JOB, never executable text."""
import json
import os
import traceback
from pathlib import Path

from pymol import cmd


def render():
    job = json.loads(Path(os.environ["BOLTZ_RENDER_JOB"]).read_text(encoding="utf-8"))
    stage = Path(job["stage"])
    aligned = stage / "aligned"
    aligned.mkdir(exist_ok=True)
    colors = ["marine", "orange", "forest", "magenta", "cyan"]
    results = []
    cmd.reinitialize()
    cmd.set("max_threads", 4)
    for index, row in enumerate(job["rows"]):
        name = f"model_{index}"
        cmd.load(str(stage / row["model"]), name)
        selection = f"{name} and chain A and name CA"
        count = cmd.count_atoms(selection)
        if count != job["chain_a_length"]:
            raise ValueError(f"Chain A CA 수 불일치: {name}: {count}")
        if index:
            # cycles=0 keeps all corresponding C-alpha atoms, no outlier rejection.
            fit = cmd.align(selection, "model_0 and chain A and name CA", cycles=0, transform=1)
            rmsd, matched = float(fit[0]), int(fit[1])
            if matched != count:
                raise ValueError(f"일부 CA만 정렬됨: {matched}/{count}")
        else:
            rmsd, matched = 0.0, count
        cmd.save(str(aligned / row["model"]), name, state=1)
        cmd.color(colors[index], name)
        results.append({"model": row["model"], "chain_A_RMSD_A": rmsd, "aligned_CA": matched,
                        "color": colors[index]})
    cmd.hide("everything", "all")
    cmd.show("cartoon", "all")
    cmd.set("cartoon_transparency", 0.12)
    cmd.set("ray_shadows", 0)
    cmd.set("antialias", 2)
    cmd.set("orthoscopic", 1)
    cmd.bg_color("white")
    cmd.orient("all")
    cmd.zoom("all", 4)
    cmd.png(str(stage / "overlay.png"), width=1200, height=850, dpi=150, ray=1, quiet=1)
    cmd.save(str(stage / "overlay.pse"))
    (stage / "alignment.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("PyMOL: chain A alignment, PNG and session saved", flush=True)


try:
    render()
except BaseException:
    traceback.print_exc()
    cmd.quit(1)
else:
    cmd.quit(0)
