"""Reproducible Boltz-2 GPU prediction for the supplied 381-residue chain."""
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("WANDB_MODE", "disabled")
os.environ.setdefault("PYTHONUTF8", "1")


def main():
    import torch
    from boltz.main import cli

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to silently run on CPU.")
    probe = torch.ones((256, 256), device="cuda")
    (probe @ probe).sum().item()
    del probe
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    args = [
        "predict", str(ROOT / "protein.yaml"),
        "--out_dir", str(ROOT / "results"),
        "--cache", str(ROOT / "cache"),
        "--model", "boltz2", "--accelerator", "gpu", "--devices", "1",
        "--recycling_steps", "3",
        "--sampling_steps", "200", "--diffusion_samples", "5",
        "--max_parallel_samples", "1", "--num_workers", "0",
        "--preprocessing-threads", "1", "--no_kernels",
        "--output_format", "mmcif", "--write_full_pae", "--seed", "42",
    ]
    info = {
        "status": "running", "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "torch": torch.__version__, "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "gpu_total_gib": torch.cuda.get_device_properties(0).total_memory / 2**30,
        "sequence_length": 381, "args": args,
        "kernel_note": "Native Windows: standard PyTorch CUDA operations; optional cuEquivariance kernels disabled.",
    }
    (ROOT / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2), flush=True)
    start = time.time()
    try:
        cli(args, standalone_mode=False)
        models = sorted((ROOT / "results").rglob("protein_model_*.cif"))
        if len(models) != 5:
            raise RuntimeError(f"Expected 5 output structures; found {len(models)}")
        info["status"] = "completed"
        info["models"] = [str(p) for p in models]
    except BaseException:
        info["status"] = "failed"
        info["error"] = traceback.format_exc()
        raise
    finally:
        info["elapsed_seconds"] = time.time() - start
        info["peak_gpu_allocated_gib"] = torch.cuda.max_memory_allocated() / 2**30
        info["peak_gpu_reserved_gib"] = torch.cuda.max_memory_reserved() / 2**30
        (ROOT / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        print(json.dumps(info, indent=2), flush=True)


if __name__ == "__main__":
    main()
