---
license: apache-2.0
language:
- yue
- en
base_model: OpenMOSS/MOSS-TTS-Nano
pipeline_tag: text-to-speech
tags:
- text-to-speech
- cantonese
- jyutping
- onnx
- speech
---

# canto-tts-nano-v1

Open-source **Hong Kong Cantonese** text-to-speech, fine-tuned from
[MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS) (0.1B params, GPT-2 backbone, Apache-2.0).
CPU-first — runs via ONNX Runtime, no GPU required.

This repo ships the **ONNX export** consumed by the
[`canto-tts`](https://github.com/typangaa/canto-tts) Python SDK. It bundles the fine-tuned TTS
graphs, the stock (unmodified) OpenMOSS audio-codec ONNX graphs, and one baked default voice.

## Why a dedicated Cantonese fine-tune

MOSS-TTS-Nano's base pretraining is Mandarin-centric — feeding it raw Hanzi produces Mandarin-accented
output. This fine-tune instead feeds **jyutping phoneme tokens** (onset/rime/tone) for Chinese
characters, while leaving English words as plain orthography (the base model's multilingual English
prior is already good) — this is what actually yields Cantonese output with natural English
code-switching. Text→jyutping conversion is handled upstream by
[`canto-hk-g2p`](https://github.com/typangaa/canto-hk-g2p); this checkpoint only consumes phoneme
tokens, it does not do grapheme-to-phoneme itself.

## Usage

```bash
pip install canto-tts   # see https://github.com/typangaa/canto-tts for current install instructions
```

```python
from canto_tts import CantoTTS

tts = CantoTTS()  # auto-downloads this repo via huggingface_hub, cached under ~/.cache/huggingface
tts.synthesize("多謝晒，今日天氣幾好。", "hello.wav")

# English code-switching
tts.synthesize("我哋一齊去 IFC food court 食飯。", "codeswitching.wav")
```

Advanced / no-SDK usage: `browser_poc_manifest.json` describes the ONNX graph layout (prefill/decode
steps for the TTS local+global transformer, plus the codec encode/decode graphs) and carries the
baked default-voice `audio_codes` — see `canto_tts.backends.onnx_backend.OnnxBackend` in the SDK repo
for the reference ONNX Runtime session-wiring implementation.

## Gate results (N=5 repeats, Qwen3-ASR-1.7B judge)

| Gate | Set | Result | Threshold | Status |
|---|---|---|---|---|
| CER | golden_prompts (100 Cantonese sentences) | **11.82%** | < 15% | ✅ |
| Tone accuracy | same | **84.22%** | ≥ 70% | ✅ |
| Code-switch CER | same | **13.87%** | < 15% | ✅ |
| Pure-English CER | 20 English-only sentences | **9.7%** | < 15% | ✅ |
| Voice-clone CER (zero-shot) | 6 speakers × 5 targets | **10.2%** | ≤ 11% | ✅ |

Full lineage, methodology, and paired-bootstrap significance notes: see the
[GitHub repo](https://github.com/typangaa/canto-tts).

## Default voice

The single baked default voice is **this checkpoint's own unconditional (`mode="continuation"`)
output** — i.e. self-generated speech, not a copy of any identifiable real person's recording and not
borrowed from another project's demo asset. This sidesteps voice-likeness/rights questions entirely
for the shipped default. There is currently no runtime voice selection in the ONNX bundle (one baked
voice only) — multi-voice picking is planned for a future release via the underlying checkpoint's
native zero-shot voice-cloning path, not this static ONNX export.

## Known limitations

- **Single default voice** — no voice selection or cloning in this ONNX bundle.
- **Cantonese + English code-switching only** — Mandarin capability was intentionally not preserved
  (the phoneme fine-tune overrides the base model's Mandarin reading prior for Chinese characters by
  design).
- No explicit style/emotion/gender control at inference — the training schema's control fields are
  fixed to a neutral default for this checkpoint.

## License

Apache-2.0, inherited from [MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS) (OpenMOSS). The
audio codec graphs (`MOSS-Audio-Tokenizer-Nano-ONNX/`) are the stock, unmodified OpenMOSS codec,
included here only for convenience so the SDK has a single download.

Training data is privately sourced and **not released** (copyright) — only these weights are public.
