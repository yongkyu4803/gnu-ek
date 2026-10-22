"""Sequential batch controller. Stdout is a JSON event stream consumed by Tk."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from boltz_batch_core import atomic_json, collect_models, fingerprint, read_seq

ROOT = Path(__file__).resolve().parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Cancelled(Exception):
    pass


def terminate_tree(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=NO_WINDOW, timeout=20)
        else:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def find_pymol():
    candidate = shutil.which("pymol")
    if candidate:
        return candidate
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
    for candidate in base.glob("PythonSoftwareFoundation.Python.3.11_*/LocalCache/local-packages/Python311/Scripts/pymol.exe"):
        return str(candidate)
    return ""


class Batch:
    def __init__(self, folder, pymol, stop_file=None, force=False):
        self.folder = Path(folder).resolve()
        self.result = self.folder / "result"
        self.pymol = pymol or find_pymol()
        self.stop_file = Path(stop_file) if stop_file else None
        self.force = force
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.log_handle = None
        self.job_log = None
        self.lock = self.result / ".batch.lock"

    def emit(self, kind, **data):
        print(json.dumps({"kind": kind, **data}, ensure_ascii=False), flush=True)

    def log(self, message):
        message = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(message)).rstrip()
        if not message:
            return
        line = f"[{datetime.now():%H:%M:%S}] {message}"
        for handle in [self.log_handle, self.job_log]:
            if handle:
                handle.write(line + "\n")
                handle.flush()
        self.emit("log", text=line)

    def check_cancel(self):
        if self.stop_file and self.stop_file.exists():
            raise Cancelled("사용자가 중지했습니다.")

    def process(self, arguments, extra_env=None, timeout=7200):
        self.check_cancel()
        environment = os.environ.copy()
        environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        environment.update(extra_env or {})
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", env=environment,
                                   creationflags=NO_WINDOW, cwd=str(ROOT), bufsize=1)
        lines = queue.Queue()

        def read_output():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        start = time.monotonic()
        next_status = start + 20
        ended = False
        try:
            while not ended or process.poll() is None:
                self.check_cancel()
                if time.monotonic() - start > timeout:
                    raise TimeoutError(f"작업 시간 제한 {timeout // 60}분 초과")
                try:
                    line = lines.get(timeout=0.2)
                    if line is None:
                        ended = True
                    else:
                        self.log(line)
                except queue.Empty:
                    pass
                if time.monotonic() >= next_status:
                    elapsed = int(time.monotonic() - start)
                    if "boltz_batch_worker.py" in " ".join(arguments):
                        try:
                            gpu = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                                                  "--format=csv,noheader"], capture_output=True, text=True,
                                                 timeout=5, creationflags=NO_WINDOW)
                            self.log(f"실행 {elapsed}초 | GPU 사용률 / 사용 메모리 / 전체: {gpu.stdout.strip()}")
                        except (OSError, subprocess.SubprocessError):
                            self.log(f"실행 중: {elapsed}초")
                    else:
                        self.log(f"PyMOL 처리 중: {elapsed}초")
                    next_status = time.monotonic() + 20
            code = process.wait()
            if code:
                raise RuntimeError(f"프로세스 종료 코드 {code}. 바로 위 로그를 확인하세요.")
        except BaseException:
            terminate_tree(process)
            raise
        finally:
            process.stdout.close()
            reader.join(timeout=2)

    def acquire_lock(self):
        import psutil
        if self.lock.exists():
            try:
                previous = json.loads(self.lock.read_text())
                running = psutil.Process(previous["pid"])
                if abs(running.create_time() - previous["created"]) < 1:
                    raise RuntimeError("이 폴더에서 이미 배치 작업이 실행 중입니다.")
            except (psutil.NoSuchProcess, KeyError, ValueError, json.JSONDecodeError):
                pass
            self.lock.rename(self.lock.with_name(f".batch_stale_{self.run_id}.json"))
        with self.lock.open("x", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "created": psutil.Process().create_time()}, handle)

    def reusable(self, manifest, digest):
        if self.force or not manifest.exists():
            return None
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data["fingerprint"] != digest or not data.get("rendered"):
                return None
            for relative, sha in data["files"].items():
                file = self.result / relative
                if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest() != sha:
                    return None
            return data
        except (OSError, ValueError, KeyError):
            return None

    def publish(self, stage, stem, rows, records, digest, rendered):
        mapping = {stage / row["model"]: self.result / row["model"] for row in rows}
        evaluation = self.result / "evaluation"
        evaluation.mkdir(exist_ok=True)
        fields = ["model", "confidence_score", "mean_pLDDT", "pTM", "ipTM", "chains", "residues",
                  "chain_A_RMSD_A", "aligned_CA"]
        with (stage / "scores.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        atomic_json(stage / "scores.json", {"input": f"{stem}.seq", "chains": records, "models": rows,
                                           "reference": rows[0]["model"],
                                           "alignment": "chain A C-alpha, all residues, cycles=0; whole object transformed"})
        mapping[stage / "scores.csv"] = evaluation / f"{stem}.csv"
        mapping[stage / "scores.json"] = evaluation / f"{stem}.json"
        if rendered:
            mapping[stage / "overlay.png"] = self.result / "images" / f"{stem}_aligned.png"
            mapping[stage / "overlay.pse"] = self.result / "images" / f"{stem}_aligned.pse"
            for row in rows:
                mapping[stage / "aligned" / row["model"]] = self.result / "aligned" / row["model"]
        manifest = evaluation / f"{stem}.manifest.json"
        # Preserve previous exports before replacing any visible output.
        old = [p for p in mapping.values() if p.exists()]
        if manifest.exists():
            old.append(manifest)
        # On render failure, archive stale images/aligned structures instead of leaving them visible.
        stale = []
        if not rendered:
            stale = [self.result / "images" / f"{stem}_aligned.{ext}" for ext in ["png", "pse"]]
            stale += [self.result / "aligned" / row["model"] for row in rows]
            old += [p for p in stale if p.exists()]
        for path in old:
            backup = self.result / "history" / self.run_id / path.relative_to(self.result)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        for path in stale:
            if path.exists():
                path.unlink()
        for source, target in mapping.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".tmp")
            shutil.copy2(source, temp)
            temp.replace(target)
        metadata = {"fingerprint": digest, "rendered": rendered, "rows": rows,
                    "files": {str(path.relative_to(self.result)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in mapping.values()},
                    "image": str(self.result / "images" / f"{stem}_aligned.png") if rendered else None}
        atomic_json(manifest, metadata)
        return metadata

    def one(self, source):
        stem = source.stem
        self.emit("status", file=source.name, status="입력 확인")
        records = read_seq(source)
        digest = fingerprint(records)
        self.log(f"{source.name}: {len(records)} chains / {sum(len(r['sequence']) for r in records)} aa")
        for record in records:
            self.log(f"chain {record['id']} ← {record['header']} ({len(record['sequence'])} aa)")
        manifest = self.result / "evaluation" / f"{stem}.manifest.json"
        cached = self.reusable(manifest, digest)
        if cached:
            self.log("입력·설정·파일 checksum 일치: 완료된 결과 재사용")
            self.emit("result", file=source.name, **cached)
            self.emit("status", file=source.name, status="완료 (재사용)")
            return "cached"
        # Work directory includes filename identity and complete input/settings digest.
        name_hash = hashlib.sha256(source.name.encode()).hexdigest()[:12]
        work = self.result / ".boltz_work" / name_hash / digest
        if self.force:
            # A failed forced rerun must never be mistaken for the previous five models.
            work = work / f"rerun_{self.run_id}"
        work.mkdir(parents=True, exist_ok=True)
        stage = work / f"export_{self.run_id}"
        prediction = work / "boltz_results_target" / "predictions" / "target"
        rows = None
        if not self.force:
            try:
                rows = collect_models(prediction, records, stage, stem)
                self.log("검증된 기존 Boltz 결과 재사용; 평가/이미지만 다시 생성")
            except (OSError, ValueError, RuntimeError, KeyError):
                pass
        if rows is None:
            self.emit("status", file=source.name, status="MSA / GPU 예측")
            job = {"records": records, "work": str(work), "model_cache": str(ROOT / "cache"),
                   "msa_cache": str(self.result / ".msa_cache")}
            atomic_json(work / "job.json", job)
            self.process([sys.executable, "-u", str(ROOT / "boltz_batch_worker.py"), str(work / "job.json")])
            self.check_cancel()
            rows = collect_models(prediction, records, stage, stem)
        self.emit("status", file=source.name, status="평가 / PyMOL")
        rendered = False
        try:
            if not self.pymol or not Path(self.pymol).is_file():
                raise FileNotFoundError("PyMOL 실행 파일을 찾지 못했습니다. 화면에서 pymol.exe 경로를 지정하세요.")
            render_job = {"stage": str(stage), "rows": rows, "chain_a_length": len(records[0]["sequence"])}
            atomic_json(stage / "render_job.json", render_job)
            self.process([self.pymol, "-cq", str(ROOT / "render_pymol.py")],
                         {"BOLTZ_RENDER_JOB": str(stage / "render_job.json")}, timeout=600)
            alignment = json.loads((stage / "alignment.json").read_text(encoding="utf-8"))
            from PIL import Image
            with Image.open(stage / "overlay.png") as image:
                image.verify()
            if len(alignment) != 5:
                raise ValueError("PyMOL 정렬 결과 개수 불일치")
            for row, fit in zip(rows, alignment):
                if row["model"] != fit["model"]:
                    raise ValueError("정렬 결과 모델 이름 불일치")
                row.update(fit)
            rendered = True
        except Cancelled:
            raise
        except Exception as exc:
            self.log(f"PyMOL 단계 실패: {exc}. 원본 PDB 5개와 신뢰도는 저장합니다.")
        self.check_cancel()
        metadata = self.publish(stage, stem, rows, records, digest, rendered)
        self.emit("result", file=source.name, **metadata)
        self.emit("status", file=source.name, status="완료" if rendered else "PDB 완료 / 이미지 실패")
        self.log(f"저장: {stem}_0.pdb ~ {stem}_4.pdb | 최고 평균 pLDDT {rows[0]['mean_pLDDT']:.2f}")
        return "completed" if rendered else "partial"

    def run(self):
        if not self.folder.is_dir():
            raise ValueError("입력 폴더가 없습니다.")
        files = sorted((p for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() == ".seq"),
                       key=lambda p: p.name.casefold())
        if not files:
            raise ValueError("선택한 폴더에 .seq 파일이 없습니다.")
        if len({p.stem.casefold() for p in files}) != len(files):
            raise ValueError("출력 이름이 충돌하는 .seq 파일이 있습니다.")
        self.result.mkdir(exist_ok=True)
        self.acquire_lock()
        counts = {"completed": 0, "cached": 0, "partial": 0, "failed": 0}
        cancelled = False
        try:
            logs = self.result / "logs"
            logs.mkdir(exist_ok=True)
            log_path = logs / f"batch_{self.run_id}.log"
            self.log_handle = log_path.open("w", encoding="utf-8")
            self.emit("started", log=str(log_path), total=len(files))
            self.log(f"폴더: {self.folder}; {len(files)}개 파일 순차 처리; 파일당 5 models")
            self.log("MSA는 ColabFold 서버로 서열을 전송합니다. GPU 예측은 이 컴퓨터에서 실행합니다.")
            self.log("RMSD: 최고 신뢰도 모델의 chain A 모든 CA 원자 기준; 이상치 제외 없음")
            for index, source in enumerate(files):
                self.check_cancel()
                self.emit("progress", current=index, total=len(files), file=source.name)
                self.job_log = (logs / f"{source.stem}_{self.run_id}.log").open("w", encoding="utf-8")
                try:
                    outcome = self.one(source)
                    counts[outcome] += 1
                except Cancelled:
                    self.emit("status", file=source.name, status="중지")
                    raise
                except Exception:
                    counts["failed"] += 1
                    self.log(traceback.format_exc())
                    self.emit("status", file=source.name, status="실패 (로그 확인)")
                finally:
                    self.job_log.close()
                    self.job_log = None
                self.emit("progress", current=index + 1, total=len(files), file=source.name)
        except Cancelled:
            cancelled = True
            self.log("중지 완료. 완성된 파일과 재사용 가능한 중간 결과는 보존했습니다.")
        finally:
            atomic_json(self.result / "logs" / f"summary_{self.run_id}.json",
                        {"counts": counts, "cancelled": cancelled})
            self.log(f"배치 종료: {counts}; 중지={cancelled}")
            self.emit("finished", counts=counts, cancelled=cancelled)
            if self.log_handle:
                self.log_handle.close()
            self.lock.unlink(missing_ok=True)
        return 2 if cancelled else (1 if counts["failed"] or counts["partial"] else 0)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True)
    parser.add_argument("--pymol", default="")
    parser.add_argument("--stop-file")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        return Batch(args.folder, args.pymol, args.stop_file, args.force).run()
    except Exception:
        print(json.dumps({"kind": "fatal", "text": traceback.format_exc()}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
