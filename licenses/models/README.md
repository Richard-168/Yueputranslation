# 模型许可与证据

核对日期：2026-11-15。模型权重没有放入本目录。本目录保留上游许可全文、固定修订模型卡和最小必要的公开授权记录；这些第三方材料保持原有许可，不随项目代码改成 MIT。

`registry.json` 是打包使用的唯一许可决策清单，列出模型身份、固定修订或权重摘要、许可、条件和证据摘要。`sources.json` 记录下载 URL、查询日期及上游证据文件 SHA-256；其作用是复核来源，不能把声明或镜像标签自动变成授权。

| 模型 | 结果 | 随包材料 |
| --- | --- | --- |
| WenetSpeech-Yue U2++ Conformer INT8 | Apache-2.0，当前 Windows／Android 基础识别 | 原作者固定模型卡、ONNX 转换来源、Apache 全文及实际权重/tokens SHA-256；非 SenseVoice 微调 checkpoint |
| Canto-TTS-Nano / OpenMOSS codec | Apache-2.0 | Apache 全文、固定模型卡与 codec 模型卡 |
| Hy-MT2-1.8B GGUF | Apache-2.0 | 固定版本原 LICENSE.txt 和模型卡 |
| Qwen3-ASR-1.7B GGUF | Apache-2.0 | Apache 全文、原模型卡、GGUF 来源模型卡 |
| Silero VAD v4 16kHz 转换 | MIT | 上游 v4 MIT；保留 Silero Team 署名；转换来源见 [sherpa-onnx PR #2372](https://github.com/k2-fsa/sherpa-onnx/pull/2372) |
| Kim_Vocal_2 | MIT | 作者公开许可评论的必要字段、MIT 告知、作者署名；不虚构版权年份 |
| MeloTTS zh_en INT8 | MIT | 固定转换仓库 MyShell.ai 原始许可、模型卡及字典告知 |
| 旧 SenseVoice Small INT8 | 自定义协议适用性未决，已退出运行／发布配置 | 保留既有证据用于历史核查；不再进入新模型包 |
| 旧 Huayan 普通话音色 | 数据许可 Unknown，退出默认流程 | 原始模型卡，保留问题证据；不进入新默认安装包 |
| Android 原 Xiaomai 粤语音色 | 未获明确模型许可，已退出运行／发布配置 | 固定仓库文件列表及元数据保留历史；改用用户已安装的系统离线粤语音色，不分发其权重 |

`Kim_Vocal_2-MIT.txt` 是按作者明确 MIT 授权整理的标准许可告知，保留作者姓名；它不是从未提供 LICENSE 的镜像仓库复制出的文件。[2026-04-22 作者原评论](https://github.com/KimberleyJensen/Mel-Band-Roformer-Vocal-Model/issues/18#issuecomment-4296256618)明确把 MIT 适用范围扩展到 Kim_Vocal_2。该许可仅对所列模型有效，不能扩展到 UVR 的全部模型。

SenseVoice 的第 2 条许可与责任章节需一起阅读；不能直接称为 MIT、Apache 或“禁止商用”。[当前维护者说明](https://github.com/modelscope/FunASR/issues/3715#issuecomment-5771978258)指出早先答复不是最终许可方确认。本项目没有替许可方解决该争议，而是选用具有独立 Apache 许可依据的 U2++ 权重，使当前发布不再依赖该争议。

检查命令：

```powershell
python tools/model_licenses.py windows
python tools/model_licenses.py android
```

当前两个 profile 的模型许可检查均应返回零；将未决模型加入 profile、缺少或修改许可证据时仍失败。历史条目保留未决状态，不会因为退出 profile 而被改成“已授权”。系统离线粤语语音由用户安装并按提供者条款使用，不属于本项目再分发资源。

各准备工具的 `--check-licenses` 可验证接线而不生成文件。`--private-development` 只产生明确的开发用途标记，不授予使用或公开分发权。Wenet 的权重和词表在生成模型包时也按本目录固定 SHA-256 核验。

新增模型、改变修订、模型文件或上游条款后须重新核验来源及条件，更新证据与摘要，并重建实际产物。许可检查不是恶意软件扫描、完整依赖许可审计、实际权重来源鉴定或公开发布批准。已经存在的安装包和 Release 附件不会被本次源码改动自动更新，未重建并核验前不能声称它们已修复。
