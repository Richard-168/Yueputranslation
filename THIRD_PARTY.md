# 第三方模型与组件

本仓库的 MIT 许可只覆盖本项目原创代码。以下资源不随源码仓库或 Python wheel 分发；下载后的许可文件应保留在本地。是否可以再分发、商用及在哪些地区使用，需按对应版本的上游许可逐项核对，本表不是安装包授权审计结论。

| 组件 | 用途 | 固定来源或版本 |
| --- | --- | --- |
| [SenseVoice-Small ONNX](https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17) | 语音识别 | `2365baeacb507f821a0c8120fcee3d484dba7a07`，INT8 |
| [Hy-MT2-1.8B GGUF](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF) | 默认翻译 | `a0c709d9fac510f2c807aa3af52872340dc37a4a`，Q4_K_M |
| [Canto-TTS-Nano](https://huggingface.co/typangaa/canto-tts-nano) | 粤语合成 | `fe17418a293d9be85685ddf750b0cfef9c88abb4` |
| [Piper zh_CN-huayan-medium](https://huggingface.co/csukuangfj/vits-piper-zh_CN-huayan-medium) | 普通话合成 | `8baec97632a57257b09073b7986f4d319efdc29a`；含模型卡和音素资源 |
| [Silero VAD / sherpa-onnx 资源](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models) | 语音分段 | `silero_vad.onnx`，SHA-256 `9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6` |
| [llama.cpp](https://github.com/ggml-org/llama.cpp/releases/tag/b12314) | 本地翻译推理程序 | `b12314` Windows CPU x64 |

模型准备脚本固定仓库修订版本并验证文件元数据中的摘要；下载档案写到本地 `outputs/`。部分发布资源依赖上游提供的摘要，普通话压缩包会再与固定模型快照核对。

Python 直接依赖在 `pyproject.toml` 中声明，包括 Qt / PySide6、sherpa-onnx、ONNX Runtime、Canto-TTS、OpenCC、音频与数字处理库。Qt/PySide6 含独立许可义务；制作桌面安装包时还需检查所用 Qt 模块、动态链接方式、许可证及告知文件。`piper-phonemize` 使用上游 Windows CPython 3.12 wheel，而非假定 PyPI 存在同名版本。

诊断脚本还可使用 Qwen3 / Qwen3-ASR、旧版 HY-MT 等候选。这些不是默认运行链路，候选许可也不由默认模型或本项目的许可替代。用户录音、音乐和歌词不属于本项目源码授权范围，不作为测试资产发布。
