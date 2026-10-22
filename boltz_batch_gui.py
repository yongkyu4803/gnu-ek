"""Two-column desktop UI for local Boltz batch modelling."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from PIL import Image, ImageTk

from boltz_batch_core import read_seq
from boltz_batch_runner import NO_WINDOW, ROOT, find_pymol


class App(tk.Tk):
    def __init__(self, initial_folder=None):
        super().__init__()
        self.title("Boltz Batch · 단백질 / 복합체 모델링")
        self.geometry("1400x980")
        self.minsize(1050, 760)
        self.configure(bg="#edf2f7")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.events = queue.Queue()
        self.process = None
        self.stop_file = None
        self.pending_close = False
        self.closed = False
        self.results = {}
        self.items = {}
        self.original_image = None
        self.preview_photo = None
        self.folder = tk.StringVar(value=str(Path(initial_folder or Path.cwd()).resolve()))
        self.pymol = tk.StringVar(value=find_pymol())
        self.force = tk.BooleanVar(value=False)
        self.overall = tk.StringVar(value="폴더를 선택하고 실행하세요.")
        self.log_path = tk.StringVar(value="로그 파일: 실행 시 result/logs에 저장")
        self.preview_title = tk.StringVar(value="중첩 이미지 · 파일을 선택하세요")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#edf2f7")
        style.configure("TLabel", background="#edf2f7", font=("맑은 고딕", 10))
        style.configure("Title.TLabel", font=("맑은 고딕", 20, "bold"), foreground="#16324f")
        style.configure("Heading.TLabel", font=("맑은 고딕", 11, "bold"), foreground="#16324f")
        style.configure("TButton", font=("맑은 고딕", 10), padding=6)
        style.configure("Treeview", rowheight=29, font=("맑은 고딕", 9))
        style.configure("Treeview.Heading", font=("맑은 고딕", 9, "bold"))
        self.build()
        self.scan()
        self.after(100, self.poll)

    def build(self):
        banner = ttk.Frame(self, padding=(20, 14))
        banner.pack(fill="x")
        ttk.Label(banner, text="Boltz Batch", style="Title.TLabel").pack(side="left")
        ttk.Label(banner, text="  서열 → 5개 모델 → 신뢰도 평가 → chain A 중첩", foreground="#52657a").pack(side="left", padx=15)
        panels = ttk.Panedwindow(self, orient="horizontal")
        panels.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        left = ttk.Frame(panels, padding=12, width=365)
        right = ttk.Frame(panels, padding=12)
        panels.add(left, weight=0)
        panels.add(right, weight=1)
        ttk.Label(left, text="01  입력 폴더", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(left, textvariable=self.folder, wraplength=315, foreground="#345676").pack(fill="x", pady=8)
        buttons = ttk.Frame(left)
        buttons.pack(fill="x")
        self.browse_button = ttk.Button(buttons, text="폴더 선택", command=self.choose_folder)
        self.browse_button.pack(side="left", fill="x", expand=True)
        self.refresh_button = ttk.Button(buttons, text="새로고침", command=self.scan)
        self.refresh_button.pack(side="left", padx=(6, 0))
        ttk.Label(left, text=".seq 파일 · FASTA 순서가 chain A, B, C…", foreground="#52657a").pack(anchor="w", pady=(12, 5))
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        self.files = ttk.Treeview(tree_frame, columns=("file", "chains", "status"), show="headings", selectmode="browse")
        for column, label, width in [("file", "파일", 145), ("chains", "체인", 45), ("status", "상태", 135)]:
            self.files.heading(column, text=label)
            self.files.column(column, width=width, minwidth=35)
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.files.yview)
        self.files.configure(yscrollcommand=scroll.set)
        self.files.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.files.tag_configure("done", foreground="#14805e")
        self.files.tag_configure("error", foreground="#b34242")
        self.files.bind("<<TreeviewSelect>>", self.select_file)
        ttk.Label(left, text="02  실행", style="Heading.TLabel").pack(anchor="w", pady=(15, 5))
        ttk.Label(left, text="RTX 3060 · 파일별 순차 처리\n5개 후보 / 동시 샘플 1개 / seed 42", foreground="#52657a").pack(anchor="w")
        self.force_check = ttk.Checkbutton(left, text="완료된 결과도 다시 계산", variable=self.force)
        self.force_check.pack(anchor="w", pady=6)
        self.start_button = ttk.Button(left, text="전체 모델링 시작", command=self.start)
        self.start_button.pack(fill="x", pady=3)
        self.stop_button = ttk.Button(left, text="현재 작업 중지", command=self.stop, state="disabled")
        self.stop_button.pack(fill="x", pady=3)
        ttk.Progressbar(left, variable=None, maximum=100, name="batch_progress").pack(fill="x", pady=(9, 5))
        self.progress = left.nametowidget("batch_progress")
        ttk.Label(left, textvariable=self.overall, wraplength=320).pack(fill="x", pady=4)
        ttk.Button(left, text="result 폴더 열기", command=self.open_result).pack(fill="x", pady=7)
        ttk.Label(left, text="PyMOL 실행 파일", style="Heading.TLabel").pack(anchor="w", pady=(8, 4))
        self.pymol_entry = ttk.Entry(left, textvariable=self.pymol)
        self.pymol_entry.pack(fill="x")
        self.pymol_button = ttk.Button(left, text="pymol.exe 지정", command=self.choose_pymol)
        self.pymol_button.pack(fill="x", pady=4)
        ttk.Label(left, text="MSA 생성 시 서열을 ColabFold 서버에 전송합니다.\n예측 모델은 실험 구조가 아닙니다.",
                  foreground="#687a8d", wraplength=320, font=("맑은 고딕", 9)).pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text="실시간 진행 로그", style="Heading.TLabel").pack(anchor="w")
        self.log_widget = ScrolledText(right, height=11, wrap="word", bg="#102235", fg="#dce8f3",
                                      insertbackground="white", font=("Consolas", 10), relief="flat", padx=10, pady=8)
        self.log_widget.pack(fill="both", expand=False, pady=(6, 4))
        self.log_widget.configure(state="disabled")
        ttk.Label(right, textvariable=self.log_path, wraplength=850, font=("맑은 고딕", 8), foreground="#687a8d").pack(anchor="w")
        ttk.Separator(right).pack(fill="x", pady=10)
        ttk.Label(right, textvariable=self.preview_title, style="Heading.TLabel").pack(anchor="w")
        self.canvas = tk.Canvas(right, background="white", height=300, highlightthickness=1, highlightbackground="#d8e2ec")
        self.canvas.pack(fill="both", expand=True, pady=(7, 4))
        self.canvas.bind("<Configure>", lambda _: self.draw_image())
        ttk.Label(right, text="0 파랑  ·  1 주황  ·  2 초록  ·  3 자홍  ·  4 청록   |   chain A로 정렬, 복합체 전체 표시",
                  foreground="#52657a", font=("맑은 고딕", 9)).pack(anchor="w")
        self.scores = ttk.Treeview(right, columns=("model", "plddt", "ptm", "iptm", "rmsd"), show="headings", height=5)
        for key, title, width in [("model", "모델", 180), ("plddt", "pLDDT /100", 105), ("ptm", "pTM", 90),
                                  ("iptm", "ipTM", 90), ("rmsd", "A RMSD (Å)", 115)]:
            self.scores.heading(key, text=title)
            self.scores.column(key, width=width, anchor="w" if key == "model" else "center")
        self.scores.pack(fill="x", pady=(8, 4))
        ttk.Label(right, text="RMSD는 모델 0 대비 chain A 전체 Cα 기준입니다. 낮은 RMSD가 구조의 정확성을 보장하지는 않습니다.",
                  wraplength=850, font=("맑은 고딕", 8), foreground="#687a8d").pack(anchor="w")

    def append_log(self, text):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n")
        # Bound UI memory; the complete log remains on disk.
        lines = int(self.log_widget.index("end-1c").split(".")[0])
        if lines > 6000:
            self.log_widget.delete("1.0", f"{lines - 5000}.0")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def choose_folder(self):
        path = filedialog.askdirectory(initialdir=self.folder.get())
        if path:
            self.folder.set(path)
            self.scan()

    def choose_pymol(self):
        path = filedialog.askopenfilename(title="PyMOL 실행 파일", filetypes=[("실행 파일", "*.exe"), ("모든 파일", "*")])
        if path:
            self.pymol.set(path)

    def scan(self):
        self.files.delete(*self.files.get_children())
        self.items.clear()
        self.results.clear()
        folder = Path(self.folder.get())
        paths = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".seq"),
                       key=lambda p: p.name.casefold()) if folder.is_dir() else []
        for index, path in enumerate(paths):
            tag = ""
            try:
                records = read_seq(path)
                count = len(records)
                status = "대기"
            except (ValueError, OSError) as exc:
                count, status, tag = "—", "입력 오류", "error"
                self.append_log(f"{path.name}: {exc}")
            item = str(index)
            self.items[path.name] = item
            self.files.insert("", "end", iid=item, values=(path.name, count, status), tags=(tag,))
            manifest = folder / "result" / "evaluation" / f"{path.stem}.manifest.json"
            if manifest.exists():
                try:
                    metadata = json.loads(manifest.read_text(encoding="utf-8"))
                    from boltz_batch_core import fingerprint
                    if count != "—" and metadata.get("fingerprint") == fingerprint(records):
                        self.results[path.name] = metadata
                        self.set_status(path.name, "저장 결과 있음")
                except (ValueError, OSError):
                    pass
        self.overall.set(f"{len(paths)}개 .seq 파일 · 파일별 5개 모델")
        self.original_image = None
        self.scores.delete(*self.scores.get_children())
        self.draw_image()
        if paths:
            self.files.selection_set("0")
        self.start_button.configure(state="normal" if paths else "disabled")

    def set_status(self, filename, status):
        item = self.items.get(filename)
        if item is not None:
            self.files.set(item, "status", status)
            self.files.item(item, tags=("error" if "실패" in status else "done" if "완료" in status else "",))

    def select_file(self, _=None):
        selection = self.files.selection()
        if not selection:
            return
        name = self.files.item(selection[0], "values")[0]
        metadata = self.results.get(name, {})
        self.preview_title.set(f"{name} · chain A 중첩" if metadata else f"{name} · 결과 대기")
        self.scores.delete(*self.scores.get_children())
        for row in metadata.get("rows", []):
            def number(key, decimals=3):
                value = row.get(key)
                return "—" if value is None else f"{value:.{decimals}f}"
            self.scores.insert("", "end", values=(row["model"], number("mean_pLDDT", 2), number("pTM"),
                                                    number("ipTM"), number("chain_A_RMSD_A")))
        self.original_image = None
        image = metadata.get("image")
        if image and Path(image).exists():
            try:
                with Image.open(image) as opened:
                    self.original_image = opened.convert("RGB").copy()
            except OSError as exc:
                self.append_log(f"이미지 읽기 실패: {exc}")
        self.draw_image()

    def draw_image(self):
        self.canvas.delete("all")
        width, height = max(10, self.canvas.winfo_width()), max(10, self.canvas.winfo_height())
        if self.original_image is None:
            self.canvas.create_text(width / 2, height / 2, text="PyMOL 중첩 이미지가 여기에 표시됩니다.",
                                    fill="#7e8fa0", font=("맑은 고딕", 12))
        else:
            resized = self.original_image.copy()
            resized.thumbnail((width - 8, height - 8), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(resized)
            self.canvas.create_image(width / 2, height / 2, image=self.preview_photo)

    def start(self):
        if self.process:
            return
        folder = Path(self.folder.get())
        if not folder.is_dir():
            messagebox.showerror("폴더 오류", "입력 폴더를 확인하세요.")
            return
        if not Path(self.pymol.get()).is_file():
            messagebox.showerror("PyMOL 경로", "이미지 생성에 사용할 pymol.exe를 지정하세요.")
            return
        result = folder / "result"
        try:
            result.mkdir(exist_ok=True)
            self.stop_file = result / f".stop_{uuid.uuid4().hex}"
            arguments = [sys.executable, "-u", str(ROOT / "boltz_batch_runner.py"), "--folder", str(folder),
                         "--pymol", self.pymol.get(), "--stop-file", str(self.stop_file)]
            if self.force.get():
                arguments.append("--force")
            environment = os.environ.copy()
            environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
            self.process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, encoding="utf-8", errors="replace", env=environment,
                                            creationflags=NO_WINDOW, cwd=str(ROOT))
        except OSError as exc:
            messagebox.showerror("실행 오류", str(exc))
            return
        self.active_controls(True)
        self.progress.configure(value=0)
        self.append_log("새 배치 실행을 시작합니다.")
        process = self.process

        def read():
            for line in process.stdout:
                try:
                    self.events.put(json.loads(line))
                except ValueError:
                    self.events.put({"kind": "log", "text": line.rstrip()})
            process.stdout.close()
            self.events.put({"kind": "exit", "code": process.wait()})
        threading.Thread(target=read, daemon=True).start()

    def active_controls(self, active):
        for widget in [self.start_button, self.browse_button, self.refresh_button,
                       self.pymol_button, self.pymol_entry, self.force_check]:
            widget.configure(state="disabled" if active else "normal")
        self.stop_button.configure(state="normal" if active else "disabled")

    def stop(self):
        if self.process and self.stop_file:
            self.stop_file.write_text("stop", encoding="ascii")
            self.stop_button.configure(state="disabled")
            self.overall.set("작업 중지 중… 완성된 결과는 보존합니다.")

    def poll(self):
        for _ in range(250):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self.handle(event)
            if self.closed:
                return
        if not self.closed:
            self.after(100, self.poll)

    def handle(self, event):
        kind = event.get("kind")
        if kind in {"log", "fatal"}:
            self.append_log(event["text"])
            if kind == "fatal":
                self.overall.set("실행 오류 · 로그를 확인하세요.")
        elif kind == "started":
            self.log_path.set("로그: " + event["log"])
        elif kind == "status":
            self.set_status(event["file"], event["status"])
        elif kind == "progress":
            self.progress.configure(value=100 * event["current"] / event["total"])
            self.overall.set(f"{event['current']}/{event['total']} 처리 · {event['file']}")
        elif kind == "result":
            self.results[event["file"]] = event
            self.files.selection_set(self.items[event["file"]])
            self.select_file()
        elif kind == "finished":
            counts = event["counts"]
            text = (f"완료 {counts['completed']} · 재사용 {counts['cached']} · "
                    f"이미지 실패 {counts['partial']} · 실패 {counts['failed']}")
            self.overall.set(("중지됨 · " if event["cancelled"] else "배치 종료 · ") + text)
            self.append_log(self.overall.get())
        elif kind == "exit":
            self.process = None
            self.active_controls(False)
            if self.stop_file:
                self.stop_file.unlink(missing_ok=True)
            self.append_log(f"실행 프로세스 종료 (code {event['code']})")
            if self.pending_close:
                self.closed = True
                self.destroy()

    def open_result(self):
        path = Path(self.folder.get()) / "result"
        if path.is_dir():
            os.startfile(str(path))
        else:
            messagebox.showinfo("result", "실행을 시작하면 result 폴더가 생성됩니다.")

    def close(self):
        if self.process:
            self.pending_close = True
            self.stop()
        else:
            self.closed = True
            self.destroy()


if __name__ == "__main__":
    App(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
