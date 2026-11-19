"""Cancellation shared by local and optional cloud inference."""

import threading
from collections import deque


class InferenceCancelled(Exception):
    pass


class PlaybackUnavailable(RuntimeError):
    """The audio worker has already reported a device failure for this task."""


class IncompleteSpeech(RuntimeError):
    """The speech model stopped before completing an utterance."""


def check_cancel(cancel):
    if cancel.is_set():
        raise InferenceCancelled()


def speak_translation(
    engine, text, target, number_mode, player, cancel, emit, first_audio=lambda: None
):
    """Optional speech must not discard a translation that has already been delivered."""
    try:
        engine.speak(text, target, number_mode, player, cancel, first_audio)
    except InferenceCancelled:
        raise
    except PlaybackUnavailable:
        check_cancel(cancel)
        return False
    except IncompleteSpeech as exc:
        check_cancel(cancel)
        emit("speech_warning", f"{exc} 完整译文已保留。")
        return False
    except Exception:
        check_cancel(cancel)
        voice = "粤语" if target == "yue" else "普通话"
        emit("speech_warning", f"{voice}自动播报失败，本次自动播报已停止。译文已保留，可稍后重播。")
        return False
    return True


class LiveSpeech:
    """One bounded worker prepares the selected voice and speaks confirmed translations."""

    def __init__(self, session, engine, player, cancel, emit):
        self.session = session
        self.engine = engine
        self.player = player
        self.cancel = cancel
        self.emit = emit
        self.waiting = deque()
        self.changed = threading.Condition()
        self.finished = False
        self.thread = None

    def _start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name="live-speech", daemon=True)
            self.thread.start()

    def prepare(self):
        """A first valid local caption lets the voice load while ASR/MT continue."""
        if self.session.autoplay and self.thread is None:
            with self.changed:
                if not self.finished and not self.cancel.is_set():
                    self._start()

    def submit(self, text):
        with self.changed:
            if not self.session.autoplay or self.cancel.is_set() or self.finished:
                return
            if len(self.waiting) >= 2:
                self.session.autoplay = False
                self.emit(
                    "speech_warning",
                    "待播译文已满。本句及后续译文可手动重播，已排队的译音会继续播放。",
                )
                return
            self.waiting.append(text)
            self._start()
            self.changed.notify()

    def _run(self):
        target = "zh" if self.session.source == "yue" else "yue"
        try:
            prepare_voice = getattr(self.engine, "prepare_voice", None)
            if prepare_voice is not None:
                try:
                    prepare_voice(target, self.cancel)
                except InferenceCancelled:
                    return
                except Exception:
                    with self.changed:
                        self.session.autoplay = False
                        self.waiting.clear()
                    if not self.cancel.is_set():
                        self.emit(
                            "speech_warning", "当前译音未能加载，已停用本次自动播报。字幕将继续。"
                        )
                    return
            while True:
                with self.changed:
                    self.changed.wait_for(
                        lambda: self.waiting or self.finished or self.cancel.is_set()
                    )
                    if self.cancel.is_set() or not self.waiting:
                        return
                    text = self.waiting.popleft()
                if not speak_translation(
                    self.engine,
                    text,
                    target,
                    self.session.number_mode,
                    self.player,
                    self.cancel,
                    self.emit,
                ):
                    with self.changed:
                        self.session.autoplay = False
                        self.waiting.clear()
                    return
        except InferenceCancelled:
            return

    def finish(self):
        with self.changed:
            self.finished = True
            self.changed.notify_all()
        if self.thread is not None:
            self.thread.join()
