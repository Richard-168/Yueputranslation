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
| [Qwen3-ASR-1.7B GGUF](https://huggingface.co/ggml-org/Qwen3-ASR-1.7B-GGUF) | 可选歌曲识别 | `36a678687ba7d07a74ca70ccb0e36902e005fb80`，Q8_0 及对应音频投影模型；原始模型为 Qwen/Qwen3-ASR-1.7B |
| [Kim_Vocal_2](https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_2.onnx) | 可选歌曲文件人声分离 | 上游资产 `108817997`，SHA-256 `ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b`；不随源码分发，安装包再分发许可尚需核对 |

模型准备脚本固定仓库修订版本并验证文件元数据中的摘要；下载档案写到本地 `outputs/`。部分发布资源依赖上游提供的摘要，普通话压缩包会再与固定模型快照核对。

Python 直接依赖在 `pyproject.toml` 中声明，包括 Qt / PySide6、sherpa-onnx、ONNX Runtime、Canto-TTS、OpenCC、音频与数字处理库。Qt/PySide6 含独立许可义务；制作桌面安装包时还需检查所用 Qt 模块、动态链接方式、许可证及告知文件。`piper-phonemize` 使用上游 Windows CPython 3.12 wheel，而非假定 PyPI 存在同名版本。

`vocals.py` 的频谱布局与重建方式参考 [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) 的 MDX 实现（MIT，Copyright © 2023 karaokenerds），使用独立 NumPy 适配器；该代码许可不覆盖 Kim_Vocal_2 模型权重。上游告知文件位于 `licenses/python-audio-separator.txt`。

诊断脚本还可使用 Qwen3、Qwen3-ASR 0.6B、旧版 HY-MT 等候选。候选许可也不由默认模型或本项目的许可替代。用户录音、音乐和歌词不属于本项目源码授权范围，不作为测试资产发布。

可选联网增强调用阿里云百炼的 [Qwen3-ASR-Flash](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference) 和 [Qwen-MT-Flash](https://help.aliyun.com/zh/model-studio/qwen-mt-api)，不分发云端模型权重，不使用项目方共享密钥。用户自行提供相应地域的账号密钥并承担费用；可用性、内容处理与计费遵循服务商协议，不受本仓库 MIT 许可替代。
