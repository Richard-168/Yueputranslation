"""Local, pinned model factories; no downloads during inference."""

from .offline import enable
from .paths import DATA_DIR

enable()
MODELS = DATA_DIR / "models"


def recognizer(language=""):
    import sherpa_onnx

    if language not in {"", "zh", "yue", "en"}:
        raise ValueError(
            "Only automatic, Mandarin, Cantonese and English recognition are supported"
        )
    return sherpa_onnx.OfflineRecognizer.from_wenet_ctc(
        model=str(MODELS / "asr-wenet/model.int8.onnx"),
        tokens=str(MODELS / "asr-wenet/tokens.txt"),
        num_threads=4,
        provider="cpu",
    )


def canto_engine():
    from canto_tts import CantoTTS

    return CantoTTS(checkpoint=str(MODELS / "canto"), backend="onnx", thread_count=4)


def mandarin_engine():
    import sherpa_onnx

    base = MODELS / "tts-zh"
    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(base / "model.int8.onnx"),
                tokens=str(base / "tokens.txt"),
                lexicon=str(base / "lexicon.txt"),
                dict_dir=str(base / "dict"),
            ),
            num_threads=4,
            provider="cpu",
        ),
        rule_fsts=",".join(str(base / name) for name in ("date.fst", "number.fst", "phone.fst")),
    )
    if not config.validate():
        raise RuntimeError("Mandarin TTS configuration invalid")
    return sherpa_onnx.OfflineTts(config)
