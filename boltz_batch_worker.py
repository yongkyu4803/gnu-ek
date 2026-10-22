"""One isolated GPU process per .seq file, releasing memory after each job."""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ["WANDB_MODE"] = "disabled"
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def main():
    import torch
    from boltz.main import cli
    from boltz_batch_core import prepare_input

    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    work = Path(job["work"])
    print("[단계 1/4] CUDA와 입력 확인", flush=True)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU를 사용할 수 없습니다. CPU로 자동 전환하지 않습니다.")
    print(f"GPU: {torch.cuda.get_device_name(0)} / torch {torch.__version__}", flush=True)
    print("[단계 2/4] MSA 생성/캐시 확인 (ColabFold 서버)", flush=True)
    target = prepare_input(job["records"], work, Path(job["msa_cache"]), print)
    print("[단계 3/4] Boltz-2 GPU 예측: 5 samples, 한 번에 1개", flush=True)
    torch.cuda.reset_peak_memory_stats()
    cli(["predict", str(target), "--out_dir", str(work), "--cache", job["model_cache"],
         "--model", "boltz2", "--accelerator", "gpu", "--devices", "1",
         "--recycling_steps", "3", "--sampling_steps", "200", "--diffusion_samples", "5",
         "--max_parallel_samples", "1", "--num_workers", "0", "--preprocessing-threads", "1",
         "--no_kernels", "--output_format", "mmcif", "--write_full_pae", "--seed", "42",
         "--override"], standalone_mode=False)
    print(f"GPU 최대 할당 {torch.cuda.max_memory_allocated()/2**30:.2f} GiB / "
          f"예약 {torch.cuda.max_memory_reserved()/2**30:.2f} GiB", flush=True)
    expected = work / "boltz_results_target" / "predictions" / "target"
    if len(list(expected.glob("target_model_*.cif"))) != 5:
        raise RuntimeError("Boltz가 완전한 5개 모델을 생성하지 못했습니다. 위 로그를 확인하세요.")
    print("[단계 4/4] 5개 CIF 생성 완료", flush=True)


if __name__ == "__main__":
    main()
