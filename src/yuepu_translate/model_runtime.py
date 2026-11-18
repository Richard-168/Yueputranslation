"""Local, pinned model factories; no downloads during inference."""

from .offline import enable
from .paths import DATA_DIR

enable()
MODELS = DATA_DIR / "models"


def require_models(*paths):
    for path in paths:
        if not (MODELS / path).is_file():
            raise RuntimeError(f"缺少本次功能所需的离线模型文件：{MODELS / path}")


def recognizer(language=""):
    import sherpa_onnx

    if language not in {"", "zh", "yue", "en"}:
        raise ValueError(
            "Only automatic, Mandarin, Cantonese and English recognition are supported"
        )
    require_models("asr-wenet/model.int8.onnx", "asr-wenet/tokens.txt")
    return sherpa_onnx.OfflineRecognizer.from_wenet_ctc(
        model=str(MODELS / "asr-wenet/model.int8.onnx"),
        tokens=str(MODELS / "asr-wenet/tokens.txt"),
        num_threads=4,
        provider="cpu",
    )


def canto_engine():
    from canto_tts import CantoTTS

    require_models("canto/browser_poc_manifest.json")
    return CantoTTS(checkpoint=str(MODELS / "canto"), backend="onnx", thread_count=4)


def mandarin_engine():
    import sherpa_onnx

    require_models("tts-zh/model.int8.onnx", "tts-zh/tokens.txt", "tts-zh/lexicon.txt")
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
