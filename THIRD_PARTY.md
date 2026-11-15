# 第三方模型与组件

本仓库的 MIT 许可只覆盖本项目原创代码。模型权重不随源码仓库或 Python wheel 分发；许可证、模型卡及授权证据保存在 [`licenses/models/`](licenses/models/README.md)，由 Windows 安装数据和 Android 模型包携带。2026-11-15 的逐项结果及未决事项如下；这不是整个软件的公开发布批准。

| 组件 | 用途 | 固定来源或版本 |
| --- | --- | --- |
| [WenetSpeech-Yue U2++ CTC ONNX](https://huggingface.co/csukuangfj/sherpa-onnx-wenetspeech-yue-u2pp-conformer-ctc-zh-en-cantonese-int8-2025-09-10) | 普通话／粤语识别 | `c911764e8227cf372ee60adc75f7f407e5b8c905`，INT8；原作者 [ASLP-lab/WSYue-ASR](https://huggingface.co/ASLP-lab/WSYue-ASR) 的独立 U2++ checkpoint，Apache-2.0；不是该集合中的 SenseVoice 微调模型 |
| [Hy-MT2-1.8B GGUF](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF) | 默认翻译 | `a0c709d9fac510f2c807aa3af52872340dc37a4a`，Q4_K_M |
| [Canto-TTS-Nano](https://huggingface.co/typangaa/canto-tts-nano) | 粤语合成 | `fe17418a293d9be85685ddf750b0cfef9c88abb4` |
| [MeloTTS zh_en](https://huggingface.co/csukuangfj/vits-melo-tts-zh_en) | 普通话合成（Windows / Android） | `a0d5c6a264c0ef92d70d8661d8cc502d79627cd6`，INT8；MyShell.ai MIT，保留模型卡、许可证及字典告知 |
| [Silero VAD / sherpa-onnx 资源](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models) | 语音分段 | `silero_vad.onnx`，SHA-256 `9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6` |
| [llama.cpp](https://github.com/ggml-org/llama.cpp/releases/tag/b12314) | 本地翻译推理程序 | `b12314` Windows CPU x64 |
| [Qwen3-ASR-1.7B GGUF](https://huggingface.co/ggml-org/Qwen3-ASR-1.7B-GGUF) | 可选歌曲识别 | `36a678687ba7d07a74ca70ccb0e36902e005fb80`，Q8_0 及对应音频投影模型；原始模型为 Qwen/Qwen3-ASR-1.7B |
| [Kim_Vocal_2](https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_2.onnx) | 可选歌曲文件人声分离 | 上游资产 `108817997`，SHA-256 `ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b`；作者 Kimberley Jensen [明确授权 MIT](https://github.com/KimberleyJensen/Mel-Band-Roformer-Vocal-Model/issues/18#issuecomment-4296256618)，须随包保留其署名、许可及授权证据 |

## 模型再分发检查

- **当前发布配置的模型许可材料已核对**：WenetSpeech-Yue U2++、Canto-TTS-Nano 及其随附 OpenMOSS codec、Hy-MT2、Qwen3-ASR 为 Apache-2.0；Silero VAD、Kim_Vocal_2、MeloTTS 为 MIT。按各自许可保留作者、来源、版权及告知，修改时注明；模型许可不覆盖训练录音、用户录音或第三方音乐。
- **SenseVoice 已退出默认运行与打包流程**：旧权重采用自定义 FunASR Model License v1.1，固定转换产物适用性问题仍保留在[上游讨论](https://github.com/modelscope/FunASR/issues/3715)。本项目通过接入独立的 Apache-2.0 U2++ 模型消除对该未决权重的发布依赖，没有将旧模型重新标为 Apache，也不据此断言 SenseVoice 禁止商用。旧缓存不自动删除或回退使用。
- **旧 Huayan 普通话模型退出默认流程**：其模型卡列出数据许可 Unknown，且上游链接失效；Windows 已改用上表的 MeloTTS，不自动回退到旧模型。旧模型缓存保留在本机，不进入新安装数据。
- **Android 原粤语 VITS 已退出运行与模型包**：改为调用手机已安装、明确标记为离线的粤语系统语音。应用不复制或再分发系统语音包；语音服务由用户合法安装，并按该服务提供者的条款使用。没有合格离线音色时明确提示安装，不自动选择联网或普通话音色。

唯一机器可读许可清单为 `licenses/models/registry.json`，共同检查工具为 `tools/model_licenses.py`。当前 Windows／Android profile 均不包含 SenseVoice、旧 Huayan 或原粤语 VITS，模型许可检查可通过；未来重新混入未决模型仍拒绝公开打包。Wenet 权重及 tokens 另核对已审查的 SHA-256，防止复用目录却换回旧 checkpoint。`--check-licenses` 只检查，不写产物；`--private-development` 始终标记为开发用途，不授予模型权利。旧 payload 无许可记录或记录过期时必须重建。现有 bundle 无法证明 EXE/BIN 与传入 payload 的编译关系；旧二进制仍须重编并另验。模型许可检查通过不是完整软件公开发布批准。

模型准备脚本固定仓库修订版本并验证文件元数据中的摘要；下载档案写到本地 `outputs/`。部分发布资源依赖上游提供的摘要，普通话直接从固定 MeloTTS 快照准备，不再使用旧 Huayan 压缩包。

Python 直接依赖在 `pyproject.toml` 中声明，包括 Qt / PySide6、sherpa-onnx、ONNX Runtime、Canto-TTS、OpenCC、音频与数字处理库。Qt/PySide6 含独立许可义务；制作桌面安装包时还需检查所用 Qt 模块、动态链接方式、许可证及告知文件。默认普通话路径不再依赖 `piper-phonemize`。

`vocals.py` 的频谱布局与重建方式参考 [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) 的 MDX 实现（MIT，Copyright © 2023 karaokenerds），使用独立 NumPy 适配器；该代码许可不覆盖 Kim_Vocal_2 模型权重。上游告知文件位于 `licenses/python-audio-separator.txt`。

诊断脚本还可使用 Qwen3、Qwen3-ASR 0.6B、旧版 HY-MT 等候选。候选许可也不由默认模型或本项目的许可替代。用户录音、音乐和歌词不属于本项目源码授权范围，不作为测试资产发布。

可选联网增强调用阿里云百炼的 [Qwen3-ASR-Flash](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference) 和 [Qwen-MT-Flash](https://help.aliyun.com/zh/model-studio/qwen-mt-api)，不分发云端模型权重，不使用项目方共享密钥。用户自行提供相应地域的账号密钥并承担费用；可用性、内容处理与计费遵循服务商协议，不受本仓库 MIT 许可替代。

## Android 开发预览

Android APK 编译包含 [sherpa-onnx 2.0.1](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1)（Apache-2.0）、其 ONNX Runtime（MIT）、[llama.cpp](https://github.com/ggml-org/llama.cpp/tree/e1f7593c32e8dd782fc7addb908d0911260511ae)（MIT，固定上述提交）、Kotlin 2.1.20 标准库（Apache-2.0）及 NDK 27.2 C++ 运行库。随 APK 保存的告知文件位于 `android/app/src/main/assets/licenses/`。Gradle Wrapper 8.11.1 使用 Apache-2.0，构建工具不属于手机模型包。以上告知不构成完整公开发布审计。

Android ASR／MT／VAD 复用表内固定资源；手机播报另外使用：

| 模型 | 固定修订 |
| --- | --- |
| [vits-melo-tts-zh_en](https://huggingface.co/csukuangfj/vits-melo-tts-zh_en) | `a0d5c6a264c0ef92d70d8661d8cc502d79627cd6`，INT8，MyShell.ai MIT |
| 手机已安装的离线粤语系统语音 | 使用 Android TextToSpeech 标准 API；拒绝网络音色和未安装音色，不再分发粤语权重 |

权重不随源码或 APK 分发，由工具生成 ZIP；文件大小、SHA-256 和许可材料固定在 APK 校验清单中。旧模型包因清单不同会被拒绝，升级后须重新导入新版包。系统粤语音色的可用性、质量及实际断网行为需在目标手机验证；APK 构建成功不能代替真机验收。
