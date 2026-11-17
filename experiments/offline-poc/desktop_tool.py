"""Legacy Tk verification window, retained for comparison; launcher uses desktop_qt.py."""

from __future__ import annotations

import argparse
import queue
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, ttk

from desktop_engine import AudioPlayer, Cancelled, Engine, Microphone, Request, SystemAudio

from yuepu_translate import APP_NAME

ROOT = Path(__file__).resolve().parent
COLORS = dict(
    bg="#F8FAFC",
    card="#FFFFFF",
    text="#0F172A",
    muted="#475569",
    blue="#2563EB",
    border="#CBD5E1",
    error="#B91C1C",
)


class Window:
    def __init__(self, root, muted=False):
        self.root = root
        self.events = queue.Queue()
        self.jobs = queue.Queue(maxsize=2)
        self.cancel = threading.Event()
        self.epoch = 0
        self.pending = 0
        self.ready = False
        self.listening = False
        self.closing = False
        self.last_translation = None
        self.engine = Engine()
        self.player = AudioPlayer(
            lambda message: self.events.put((self.epoch, "audio_error", message)), muted=muted
        )
        self.microphone = None
        self.direction = tk.StringVar(value="粤语 → 普通话")
        self.audio_source = tk.StringVar(value="麦克风")
        self.auto = tk.BooleanVar(value=True)
        self.number = tk.StringVar(value="按原文")
        self.status = tk.StringVar(value="先加载离线模型，再开始交流。")
        self.source_title = tk.StringVar(value="粤语原文")
        self.target_title = tk.StringVar(value="普通话译文")
        self.options = ("yue", True, "original")
        self._build()
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()
        self.root.after(50, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Control-Return>", lambda event: self.translate_input())
        self.root.bind("<Escape>", lambda event: self.stop())

    def _build(self):
        root = self.root
        root.title(f"{APP_NAME} · Windows 离线验证工具")
        root.geometry("1140x760")
        root.minsize(940, 650)
        root.configure(bg=COLORS["bg"])
        root.option_add("*Font", ("Microsoft YaHei UI", 11))
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("TButton", padding=(14, 10), font=("Microsoft YaHei UI", 11))
        style.configure(
            "Primary.TButton", background=COLORS["blue"], foreground="white", borderwidth=0
        )
        style.map(
            "Primary.TButton",
            background=[("disabled", "#CBD5E1"), ("active", "#1D4ED8")],
            foreground=[("disabled", "#475569")],
        )
        style.configure("TCheckbutton", background=COLORS["bg"], foreground=COLORS["text"])
        shell = ttk.Frame(root, padding=28)
        shell.pack(fill="both", expand=True)
        top = ttk.Frame(shell)
        top.pack(fill="x")
        ttk.Label(top, text=APP_NAME, font=("Microsoft YaHei UI", 24, "bold")).pack(side="left")
        ttk.Label(top, text="Windows 离线验证工具", foreground=COLORS["muted"]).pack(
            side="left", padx=18, pady=(10, 0)
        )
        ttk.Label(top, text="本地处理", foreground=COLORS["blue"]).pack(side="right")
        ttk.Label(
            shell, text="面对面交流与设备音频 · 离线双向翻译", foreground=COLORS["muted"]
        ).pack(anchor="w", pady=(7, 18))

        controls = ttk.Frame(shell)
        controls.pack(fill="x", pady=(0, 12))
        ttk.Label(controls, text="翻译方向").pack(side="left", padx=(0, 10))
        self.direction_box = ttk.Combobox(
            controls,
            textvariable=self.direction,
            values=["粤语 → 普通话", "普通话 → 粤语"],
            state="readonly",
            width=20,
        )
        self.direction_box.pack(side="left")
        self.direction_box.bind("<<ComboboxSelected>>", lambda event: self.update_options())
        self.auto_box = ttk.Checkbutton(
            controls, text="自动播报", variable=self.auto, command=self.update_options
        )
        self.auto_box.pack(side="left", padx=22)
        ttk.Label(controls, text="数字读法").pack(side="left", padx=(4, 8))
        self.number_box = ttk.Combobox(
            controls,
            textvariable=self.number,
            values=["按原文", "金额", "号码逐位"],
            state="readonly",
            width=12,
        )
        self.number_box.pack(side="left")
        self.number_box.bind("<<ComboboxSelected>>", lambda event: self.update_options())

        inputs = ttk.Frame(shell)
        inputs.pack(fill="x", pady=(0, 14))
        ttk.Label(inputs, text="声音来源").pack(side="left", padx=(0, 10))
        self.audio_source_box = ttk.Combobox(
            inputs,
            textvariable=self.audio_source,
            values=["麦克风", "设备播放声音"],
            state="readonly",
            width=20,
        )
        self.audio_source_box.pack(side="left")
        self.audio_source_box.bind("<<ComboboxSelected>>", lambda event: self.change_audio_source())
        ttk.Label(
            inputs, text="设备声音收音期间仅显示字幕，停止后可播报。", foreground=COLORS["muted"]
        ).pack(side="left", padx=18)

        panes = ttk.Frame(shell)
        panes.pack(fill="both", expand=True)
        panes.columnconfigure(0, weight=1)
        panes.columnconfigure(1, weight=1)
        panes.rowconfigure(1, weight=1)
        ttk.Label(
            panes, textvariable=self.source_title, font=("Microsoft YaHei UI", 13, "bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        ttk.Label(
            panes, textvariable=self.target_title, font=("Microsoft YaHei UI", 13, "bold")
        ).grid(row=0, column=1, sticky="w", padx=(18, 0), pady=(0, 10))
        self.source = tk.Text(
            panes,
            wrap="word",
            font=("Microsoft YaHei UI", 17),
            height=4,
            width=25,
            padx=18,
            pady=18,
            bg=COLORS["card"],
            fg=COLORS["text"],
            insertbackground=COLORS["blue"],
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightcolor=COLORS["blue"],
            undo=True,
        )
        self.source.grid(row=1, column=0, sticky="nsew", padx=(0, 9))
        self.target = tk.Text(
            panes,
            wrap="word",
            font=("Microsoft YaHei UI", 17),
            height=4,
            width=25,
            padx=18,
            pady=18,
            bg=COLORS["card"],
            fg=COLORS["text"],
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightcolor=COLORS["blue"],
            state="disabled",
        )
        self.target.grid(row=1, column=1, sticky="nsew", padx=(9, 0))
        ttk.Label(
            shell,
            text="可直接输入短句；音频文件每次不超过 15 秒。Ctrl + Enter 翻译，Esc 停止。",
            foreground=COLORS["muted"],
        ).pack(anchor="w", pady=(10, 18))

        actions = ttk.Frame(shell)
        actions.pack(fill="x")
        self.load_button = ttk.Button(
            actions, text="加载离线模型", style="Primary.TButton", command=self.load
        )
        self.load_button.pack(side="left", padx=(0, 10))
        self.record_button = ttk.Button(
            actions, text="开始收音", style="Primary.TButton", command=self.toggle_microphone
        )
        self.record_button.pack(side="left", padx=(0, 10))
        self.file_button = ttk.Button(actions, text="打开音频", command=self.open_audio)
        self.file_button.pack(side="left", padx=(0, 10))
        self.translate_button = ttk.Button(actions, text="翻译输入", command=self.translate_input)
        self.translate_button.pack(side="left", padx=(0, 10))
        self.replay_button = ttk.Button(actions, text="播报译文", command=self.replay)
        self.replay_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="停止任务", command=self.stop)
        self.stop_button.pack(side="right")
        self.progress = ttk.Progressbar(shell, mode="indeterminate", length=180)
        self.progress.pack(fill="x", pady=(20, 10))
        self.status_label = ttk.Label(shell, textvariable=self.status, wraplength=1000)
        self.status_label.pack(anchor="w")
        self.footer_label = ttk.Label(
            shell,
            text="建议佩戴耳机，避免译音被再次收音。数字读法与真实对话效果仍需核对；安卓尚未验证。",
            foreground=COLORS["muted"],
            wraplength=860,
        )
        self.footer_label.pack(anchor="w", pady=(10, 0))
        root.bind("<Configure>", self._resize, add="+")
        self.update_options()
        self._buttons()

    def _resize(self, event):
        if event.widget == self.root:
            width = max(320, event.width - 56)
            self.status_label.configure(wraplength=width)
            self.footer_label.configure(wraplength=width)

    def update_options(self):
        source = "yue" if self.direction.get().startswith("粤语") else "zh"
        mode = {"按原文": "original", "金额": "amount", "号码逐位": "identifier"}[self.number.get()]
        self.options = source, self.auto.get(), mode
        self.source_title.set("粤语原文" if source == "yue" else "普通话原文")
        if self.last_translation is None:
            self.target_title.set("普通话译文" if source == "yue" else "粤语译文")

    def _buttons(self):
        idle = self.pending == 0 and not self.closing
        self.load_button.configure(state="normal" if idle and not self.ready else "disabled")
        system_audio = self.audio_source.get() == "设备播放声音"
        start_text = "翻译设备声音" if system_audio else "开始收音"
        self.record_button.configure(
            text="停止收音" if self.listening else start_text,
            state="normal" if self.listening or (self.ready and idle) else "disabled",
        )
        for widget in (self.file_button, self.translate_button):
            widget.configure(
                state="normal" if self.ready and idle and not self.listening else "disabled"
            )
        self.replay_button.configure(
            state="normal"
            if self.ready and idle and self.last_translation and not self.listening
            else "disabled"
        )
        self.stop_button.configure(
            state="normal" if self.pending or self.listening or self.player.busy else "disabled"
        )
        self.direction_box.configure(
            state="readonly" if idle and not self.listening else "disabled"
        )
        self.audio_source_box.configure(
            state="readonly" if idle and not self.listening else "disabled"
        )
        self.auto_box.configure(state="disabled" if self.listening and system_audio else "normal")
        if self.pending:
            self.progress.start(16)
        else:
            self.progress.stop()

    def _set_status(self, text, error=False):
        self.status.set(text)
        self.status_label.configure(foreground=COLORS["error"] if error else COLORS["text"])

    def change_audio_source(self):
        if self.listening or self.pending:
            return
        if self.audio_source.get() == "设备播放声音":
            self._set_status(
                "将获取 Windows 默认输出设备的播放声音。收音期间只显示字幕，避免译音循环。"
            )
        else:
            self._set_status("已选择麦克风。点击“开始收音”后获取声音。")
        self._buttons()

    def load(self):
        if self.pending or self.ready:
            return
        self.cancel.clear()
        self.pending += 1
        self.jobs.put_nowait((self.epoch, "load"))
        self._set_status("正在加载离线模型并预热，首次可能需要几十秒…")
        self._buttons()

    def _request(self, kind, **kwargs):
        source, autoplay, mode = self.options
        return Request(
            self.epoch, kind, source=source, autoplay=autoplay, number_mode=mode, **kwargs
        )

    def submit(self, request):
        if not self.ready or self.closing:
            return False
        if self.listening and self.audio_source.get() == "设备播放声音":
            if request.kind == "speak":
                return False
            request = replace(request, autoplay=False)
        try:
            self.jobs.put_nowait(request)
            self.pending += 1
            self._buttons()
            return True
        except queue.Full:
            self.stop()
            self._set_status("待处理语句过多，已停止收音。请稍停片刻后重试。", error=True)
            return False

    def translate_input(self):
        if self.pending or self.listening:
            return
        text = self.source.get("1.0", "end-1c").strip()
        if not text:
            self._set_status("请先在原文框输入短句。", error=True)
            self.source.focus_set()
            return
        if len(text) > 120:
            self._set_status("验证工具每次最多 120 字，请分句输入。", error=True)
            return
        self.cancel.clear()
        self.submit(self._request("text", text=text))

    def open_audio(self, path=None):
        if self.pending or self.listening or not self.ready:
            return
        if path is None:
            path = filedialog.askopenfilename(
                parent=self.root, title="选择不超过 15 秒的语音", filetypes=[("WAV 音频", "*.wav")]
            )
        if path:
            self.cancel.clear()
            self.submit(self._request("file", path=str(path)))

    def replay(self):
        if not self.last_translation or self.pending or self.listening:
            return
        text, target = self.last_translation
        self.cancel.clear()
        self.submit(
            Request(self.epoch, "speak", source=target, text=text, number_mode=self.options[2])
        )

    def toggle_microphone(self):
        if self.listening:
            self.stop()
            return
        if not self.ready or self.pending:
            return
        self.cancel.clear()
        self.listening = True
        epoch = self.epoch
        source, auto, mode = self.options
        system_audio = self.audio_source.get() == "设备播放声音"
        if system_audio:
            self.player.stop()

        # Capture callbacks communicate through events; they never access Tk.
        def on_segment(samples):
            self.events.put((epoch, "segment", (samples, source, auto, mode)))

        def on_error(message):
            self.events.put((epoch, "capture_error", message))

        if system_audio:
            self.microphone = SystemAudio(
                on_segment, on_error, lambda name: self.events.put((epoch, "capture_started", name))
            )
        else:
            self.microphone = Microphone(on_segment, on_error)
        self.microphone.start()
        self._set_status(
            "正在启动设备声音翻译，收音期间仅显示字幕…"
            if system_audio
            else "正在连续收音…请说短句，建议佩戴耳机。"
        )
        self._buttons()

    def stop(self):
        self.cancel.set()
        self.epoch += 1
        self.listening = False
        if self.microphone:
            self.microphone.stop()
            self.microphone = None
        self.player.stop()
        while True:
            try:
                self.jobs.get_nowait()
                self.jobs.task_done()
                self.pending = max(0, self.pending - 1)
            except queue.Empty:
                break
        self._set_status(
            "正在停止当前任务…" if self.pending else "已停止。可以调整方向或重新开始。"
        )
        self._buttons()

    def _worker(self):
        while True:
            job = self.jobs.get()
            if job is None:
                self.jobs.task_done()
                return
            epoch = job[0] if isinstance(job, tuple) else job.token

            def emit(key, value, epoch=epoch):
                self.events.put((epoch, key, value))

            try:
                if isinstance(job, tuple):
                    self.engine.load(self.cancel, lambda text: emit("status", text))
                    emit("ready", True)
                else:
                    self.engine.process(job, self.cancel, self.player, emit)
                    emit("done", True)
            except Cancelled:
                pass
            except (ValueError, RuntimeError, TimeoutError) as exc:
                emit("error", str(exc))
            except Exception:
                emit("error", "本次处理失败，请停止后重试。")
            finally:
                self.events.put((epoch, "finished", None))
                self.jobs.task_done()

    def _poll(self):
        for _ in range(100):
            try:
                epoch, kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "finished":
                self.pending = max(0, self.pending - 1)
                self._buttons()
                continue
            if epoch != self.epoch:
                continue
            if kind == "ready":
                self.ready = True
                self._set_status("离线模型已就绪。可开始收音、打开音频或输入短句。")
            elif kind == "status":
                self._set_status(value)
            elif kind == "source":
                self.source.delete("1.0", "end")
                self.source.insert("1.0", value)
            elif kind == "translation":
                self.last_translation = value["text"], value["target"]
                self.target_title.set("普通话译文" if value["target"] == "zh" else "粤语译文")
                self.target.configure(state="normal")
                self.target.delete("1.0", "end")
                self.target.insert("1.0", value["text"])
                self.target.configure(state="disabled")
                self._set_status(f"已译出，用时 {value['seconds']:.1f} 秒。")
            elif kind == "first_audio":
                self._set_status(f"译音已生成，用时 {value:.1f} 秒。")
            elif kind == "done":
                if self.listening and self.audio_source.get() == "设备播放声音":
                    self._set_status("设备声音已译出，正在继续收音…（仅字幕）")
                elif not self.options[1]:
                    self._set_status("翻译完成。可点击“播报译文”试听。")
            elif kind == "capture_started":
                self._set_status(f"正在翻译设备声音：{value}。收音期间仅显示字幕。")
            elif kind in {"capture_error", "audio_error"}:
                self.stop()
                self._set_status(value, error=True)
            elif kind == "error":
                self._set_status(value, error=True)
            elif kind == "segment" and self.listening:
                samples, source, auto, mode = value
                self.submit(
                    Request(
                        self.epoch,
                        "audio",
                        source=source,
                        samples=samples,
                        autoplay=auto,
                        number_mode=mode,
                    )
                )
        if self.closing and not self.worker.is_alive():
            self.player.close()
            self.root.destroy()
            return
        self._buttons()
        self.root.after(50, self._poll)

    def close(self):
        if self.closing:
            return
        self.stop()
        self.closing = True
        self._set_status("正在释放模型并退出…")
        self.jobs.put_nowait(None)
        self._buttons()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--muted",
        action="store_true",
        help="Verification mode: generate PCM without opening speakers",
    )
    args = parser.parse_args()
    root = tk.Tk()
    Window(root, muted=args.muted)
    root.mainloop()


if __name__ == "__main__":
    main()
