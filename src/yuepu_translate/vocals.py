"""Optional offline Kim_Vocal_2 adapter; never used by live raw-audio capture.

STFT layout follows the MIT python-audio-separator MDX implementation:
https://github.com/nomadkaraoke/python-audio-separator
Independent NumPy adapter; model assets and their licenses are not bundled.
"""

import hashlib

import numpy as np

from .local_inference import check_cancel
from .paths import DATA_DIR

MODEL_SHA256 = "ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b"


class SpectralTransform:
    def __init__(self, n_fft=7680, hop=1024):
        self.n_fft, self.hop = n_fft, hop
        self.window = np.hanning(n_fft + 1)[:-1].astype(np.float32)

    def forward(self, audio, dim_f=None):
        data = np.pad(audio, ((0, 0), (self.n_fft // 2, self.n_fft // 2)), mode="reflect")
        frames = np.lib.stride_tricks.sliding_window_view(data, self.n_fft, axis=-1)
        spectrum = np.fft.rfft(frames[:, :: self.hop, :] * self.window, axis=-1).transpose(0, 2, 1)
        packed = np.stack((spectrum.real, spectrum.imag), axis=1)
        packed = packed.reshape(1, 4, spectrum.shape[1], spectrum.shape[2])
        return np.ascontiguousarray(packed[:, :, :dim_f, :], dtype=np.float32)

    def inverse(self, packed):
        freq = self.n_fft // 2 + 1
        padded = np.pad(packed, ((0, 0), (0, 0), (0, freq - packed.shape[2]), (0, 0)))
        split = padded[0].reshape(2, 2, freq, -1)
        spectrum = split[:, 0] + 1j * split[:, 1]
        frames = np.fft.irfft(spectrum.transpose(0, 2, 1), n=self.n_fft, axis=-1) * self.window
        length = self.hop * (frames.shape[1] - 1) + self.n_fft
        result = np.zeros((2, length), dtype=np.float32)
        weights = np.zeros(length, dtype=np.float32)
        for index in range(frames.shape[1]):
            start = index * self.hop
            result[:, start : start + self.n_fft] += frames[:, index]
            weights[start : start + self.n_fft] += self.window**2
        result /= np.maximum(weights, 1e-12)
        return result[:, self.n_fft // 2 : -self.n_fft // 2]


def separate_vocals(audio, cancel, status):
    """44.1 kHz stereo -> same-size vocals; at most ten minutes, CPU only."""
    if (
        audio.ndim != 2
        or audio.shape[1] != 2
        or not 0 < len(audio) <= 600 * 44100
        or not np.isfinite(audio).all()
    ):
        raise ValueError("人声分离仅接受不超过 10 分钟的有效 44.1 kHz 双声道音频。")
    check_cancel(cancel)
    model = DATA_DIR / "models/song-separator/Kim_Vocal_2.onnx"
    if not model.is_file():
        raise RuntimeError("缺少高质量人声分离模型，请按开发说明准备；也可选择原始音频处理。")
    with model.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != MODEL_SHA256:
            raise RuntimeError("人声分离模型摘要不匹配，已停止处理。")
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = 4, 1
    session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
    transform = SpectralTransform()
    chunk, trim = 1024 * 255, 7680 // 2
    step = int(0.75 * chunk)
    padded = np.pad(audio.T, ((0, 0), (trim, trim + chunk)))
    result = np.zeros_like(padded)
    weights = np.zeros(padded.shape[1], dtype=np.float32)
    total = (padded.shape[1] + step - 1) // step
    for index, start in enumerate(range(0, padded.shape[1], step)):
        check_cancel(cancel)
        status(f"正在分离人声 {index + 1}/{total}，高质量处理需要较长时间…")
        end = min(start + chunk, padded.shape[1])
        count = end - start
        part = np.pad(padded[:, start:end], ((0, 0), (0, chunk - count)))
        spectrum = transform.forward(part, 3072)
        spectrum[:, :, :3, :] = 0
        prediction = session.run(None, {"input": spectrum})[0]
        estimate = transform.inverse(prediction)[:, :count]
        window = np.hanning(count).astype(np.float32)
        result[:, start:end] += estimate * window
        weights[start:end] += window
    check_cancel(cancel)
    valid = slice(trim, trim + len(audio))
    if not np.all(weights[valid] > 0):
        raise RuntimeError("人声分离覆盖不完整，未使用此结果。")
    vocals = ((result[:, valid] / weights[valid]) * 1.009).T
    if vocals.shape != audio.shape or not np.isfinite(vocals).all():
        raise RuntimeError("人声分离输出无效，未使用此结果。")
    return vocals
