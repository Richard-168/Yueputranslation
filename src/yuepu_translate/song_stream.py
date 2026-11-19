"""Paragraph snapshots: real pause endings, bounded context, latest-only drafts."""

from collections import deque
from dataclasses import dataclass, replace
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

    def __init__(
        self,
        emit,
        detector=None,
        pause_seconds=2.0,
        *,
        first_seconds=4.0,
        update_seconds=2.0,
        pre_roll_seconds=2.0,
        max_segment_seconds=None,
        context_seconds=30,
        overlap_seconds=8,
    ):
        if (
            not 0.25 <= first_seconds <= 4
            or not 0.25 <= update_seconds <= 4
            or not 0 <= pre_roll_seconds <= 2
            or not 0.25 <= pause_seconds <= 5
            or (max_segment_seconds is not None and not 1 <= max_segment_seconds <= 15)
            or not 4 <= context_seconds <= 30
            or not 0 < overlap_seconds < context_seconds
        ):
            raise ValueError("无效的实时字幕时间配置。")
        self.emit, self.detector = emit, detector
        self.pause_samples = round(pause_seconds * RATE)
        self.first_samples = round(first_seconds * RATE)
        self.update_samples = round(update_seconds * RATE)
        self.pre_roll_samples = round(pre_roll_seconds * RATE)
        self.context_samples = round(context_seconds * RATE)
        self.overlap_samples = round(overlap_seconds * RATE)
        self.max_segment_samples = (
            round(max_segment_seconds * RATE) if max_segment_seconds is not None else None
        )
        self.chunks = deque()
        self.retained = 0
        self.pending = np.empty(0, dtype=np.float32)
        self.end = self.block = 0
        self.origin = None
        self.paragraph_start = 0
        self.voice_end = 0
        self.next_update = 0
        self.last_final_end = 0
        self.defer_drafts = False

    def _window(self, final=False, checkpoint=False):
        end = min(self.end, self.origin + self.context_samples) if checkpoint else self.end
        start = max(self.origin, end - self.context_samples)
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
                tick + max(0, self.origin + self.context_samples - end) / RATE,
                checkpoint,
                min(self.voice_end, end),
            )
        )
        if final:
            self.last_final_end = self.end
            self.block += 1
            self.origin = None
        elif checkpoint:
            self.origin = end - self.overlap_samples
        self.next_update = end + self.update_samples

    def _accept(self, frame):
        self.chunks.append(frame.copy())
        self.retained += len(frame)
        self.end += len(frame)
        # A checkpoint can end inside the current 512-sample frame. Keep a
        # frame of headroom so its older left edge remains addressable.
        while self.retained - len(self.chunks[0]) >= self.context_samples + 512:
            self.retained -= len(self.chunks.popleft())
        voiced = (
            self.detector(frame)
            if self.detector is not None
            else bool(np.max(np.abs(frame)) >= 0.002)
        )
        if voiced:
            self.voice_end = self.end
            if self.origin is None:
                self.origin = max(self.last_final_end, self.end - self.pre_roll_samples)
                self.paragraph_start = self.origin
                self.next_update = self.origin + self.first_samples
        if self.origin is None:
            return
        if not voiced and self.end - self.voice_end >= self.pause_samples:
            self._window(final=True)
        elif (
            self.max_segment_samples is not None
            and self.end - self.paragraph_start >= self.max_segment_samples
        ):
            self._window(final=True)
        elif self.end - self.origin >= self.context_samples:
            self._window(checkpoint=True)
        elif self.end >= self.next_update and not self.defer_drafts:
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
    """FIFO confirmations, one replaceable draft, and a bounded backlog."""

    def __init__(self, max_finals=3, *, stop_at_limit=False):
        self.condition = Condition()
        self.finals = deque()
        self.draft = None
        self.finished = False
        self.cutoff_reached = False
        self.max_finals = max_finals
        self.stop_at_limit = stop_at_limit
        self.coalesced = 0
        self.last_final = -1

    @classmethod
    def for_capture(cls):
        # Enough room for bursts and model warm-up, with at most 16 audio
        # windows waiting. Capture never waits on a slow inference thread.
        return cls(max_finals=16, stop_at_limit=True)

    def put(self, window, *, cancel=None):
        with self.condition:
            if (
                self.finished
                or self.cutoff_reached
                or window.block <= self.last_final
                or (cancel is not None and cancel.is_set())
            ):
                return
            if window.final or window.checkpoint:
                while len(self.finals) >= self.max_finals:
                    if cancel is None:
                        raise SongOverload("字幕处理跟不上播放速度，待确认队列已满。")
                    self.condition.wait(0.05)
                    if self.finished or cancel.is_set() or window.block <= self.last_final:
                        return
                at_cutoff = self.stop_at_limit and len(self.finals) + 1 == self.max_finals
                if at_cutoff and window.checkpoint and not window.final:
                    # No subsequent window can be admitted to close this paragraph.
                    window = replace(window, final=True, checkpoint=False)
                self.finals.append(window)
                if window.final:
                    self.last_final = window.block
                if self.draft is not None and self.draft.block <= window.block:
                    self.coalesced += 1
                    self.draft = None
                if at_cutoff:
                    # Reject more input now; only the capture owner's finish()
                    # after its final status/flush lets the consumer exit.
                    self.cutoff_reached = True
                    self.condition.notify_all()
                    raise SongOverload("字幕处理跟不上播放速度，待确认队列已满。")
            else:
                if self.draft is not None:
                    self.coalesced += 1
                self.draft = window
            self.condition.notify()

    def get(self, cancel):
        with self.condition:
            while not cancel.is_set():
                if self.finals:
                    window = self.finals.popleft()
                    self.condition.notify_all()
                    return window
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

    def has_waiting_confirmation(self, block=None):
        with self.condition:
            if block is None:
                return bool(self.finals)
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
