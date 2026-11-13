"""Paragraph snapshots: real pause endings, bounded context, latest-only drafts."""

from collections import deque
from dataclasses import dataclass
from threading import Condition
from time import monotonic

import numpy as np

RATE = 16000


class SongOverload(RuntimeError):
    pass


@dataclass(frozen=True)
class SongWindow:
    block: int
    start: int
    end: int
    samples: np.ndarray
    final: bool
    captured_at: float
    confirm_at: float
    checkpoint: bool = False
    voice_end: int = -1

    @property
    def silent(self):
        # Development threshold, deliberately requires both conditions.
        return bool(
            np.max(np.abs(self.samples)) < 0.002
            and np.sqrt(np.mean(self.samples.astype(np.float64) ** 2)) < 0.0005
        )


class RollingAudio:
    """One paragraph until a pause/Stop; 30 s context, 8 s checkpoint overlap.

    Checkpoints preserve older stable text without creating a new UI record.
    Production supplies Silero activity; the energy default is only suitable
    for deterministic PCM tests, not for distinguishing singing from music.
    """

    def __init__(self, emit, detector=None, pause_seconds=2.0):
        self.emit, self.detector = emit, detector
        self.pause_samples = round(pause_seconds * RATE)
        self.chunks = deque()
        self.retained = 0
        self.pending = np.empty(0, dtype=np.float32)
        self.end = self.block = 0
        self.origin = None
        self.voice_end = 0
        self.next_update = 0
        self.last_final_end = 0

    def _window(self, final=False, checkpoint=False):
        end = min(self.end, self.origin + 30 * RATE) if checkpoint else self.end
        start = max(self.origin, end - 30 * RATE)
        count = end - start
        tick = monotonic()
        buffer = np.concatenate(self.chunks)
        right = len(buffer) - (self.end - end)
        audio = buffer[right - count : right].copy()
        self.emit(
            SongWindow(
                self.block,
                start,
                end,
                audio,
                final,
                tick,
                tick + max(0, self.origin + 30 * RATE - end) / RATE,
                checkpoint,
                min(self.voice_end, end),
            )
        )
        if final:
            self.last_final_end = self.end
            self.block += 1
            self.origin = None
        elif checkpoint:
            self.origin = end - 8 * RATE
        self.next_update = end + 2 * RATE

    def _accept(self, frame):
        self.chunks.append(frame.copy())
        self.retained += len(frame)
        self.end += len(frame)
        while self.retained - len(self.chunks[0]) >= 30 * RATE:
            self.retained -= len(self.chunks.popleft())
        voiced = (
            self.detector(frame)
            if self.detector is not None
            else bool(np.max(np.abs(frame)) >= 0.002)
        )
        if voiced:
            self.voice_end = self.end
            if self.origin is None:
                self.origin = max(self.last_final_end, self.end - 2 * RATE)
                self.next_update = self.origin + 4 * RATE
        if self.origin is None:
            return
        if not voiced and self.end - self.voice_end >= self.pause_samples:
            self._window(final=True)
        elif self.end - self.origin >= 30 * RATE:
            self._window(checkpoint=True)
        elif self.end >= self.next_update:
            self._window()

    def feed(self, samples):
        data = np.asarray(samples, dtype=np.float32)
        if data.ndim != 1 or not np.isfinite(data).all():
            raise ValueError("歌曲音频必须是有效的 16 kHz 单声道数据。")
        data = np.concatenate((self.pending, data))
        complete = len(data) // 512 * 512
        for offset in range(0, complete, 512):
            self._accept(data[offset : offset + 512])
        self.pending = data[complete:].copy()

    def flush(self):
        if len(self.pending):
            frame, self.pending = self.pending, np.empty(0, dtype=np.float32)
            self._accept(frame)
        if self.origin is not None:
            self._window(final=True)


class SongMailbox:
    """Coalesce drafts, preserve every final; stop explicitly on overload."""

    def __init__(self, max_finals=3):
        self.condition = Condition()
        self.finals = deque()
        self.draft = None
        self.finished = False
        self.max_finals = max_finals
        self.coalesced = 0
        self.last_final = -1

    def put(self, window):
        with self.condition:
            if self.finished or window.block <= self.last_final:
                return
            if window.final or window.checkpoint:
                if len(self.finals) >= self.max_finals:
                    raise SongOverload("歌曲识别跟不上播放速度，已停止收音。请暂停来源后重试。")
                self.finals.append(window)
                if window.final:
                    self.last_final = window.block
                if self.draft is not None and self.draft.block <= window.block:
                    self.coalesced += 1
                    self.draft = None
            else:
                if self.draft is not None:
                    self.coalesced += 1
                self.draft = window
            self.condition.notify()

    def get(self, cancel):
        with self.condition:
            while not cancel.is_set():
                if self.finals:
                    return self.finals.popleft()
                if self.draft is not None:
                    window, self.draft = self.draft, None
                    return window
                if self.finished:
                    return None
                self.condition.wait(0.05)
        return None

    def finish(self):
        with self.condition:
            self.finished = True
            self.condition.notify_all()

    def has_waiting_confirmation(self, block):
        with self.condition:
            return any(window.block == block for window in self.finals)


def trim_context(previous, current):
    """Remove exact adjacent context only, never a later chorus/global match.

    Callers normalize script before matching. Single-character coincidences
    are retained to avoid dropping a new syllable.
    """
    before = "".join(c for c in previous[-48:] if c.isalnum())
    positions = [i for i, c in enumerate(current) if c.isalnum()]
    after = "".join(current[i] for i in positions)
    for count in range(min(len(before), len(after)), 1, -1):
        if before.endswith(after[:count]):
            return current[positions[count - 1] + 1 :].lstrip(" ，。！？、；：,.!?;:\n")
    return current


def draft_fits(window, seconds_per_audio, translation_seconds, now):
    """Avoid starting a speculative decode that will delay its imminent final."""
    cost = len(window.samples) / RATE * seconds_per_audio + translation_seconds
    return window.final or window.checkpoint or now + cost <= window.confirm_at
