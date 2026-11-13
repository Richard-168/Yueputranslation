# YuePuTranslate · 粤普同传

粤语与普通话双向翻译的 Windows 桌面实验版，使用本地语音识别、翻译和语音合成模型，提供双栏字幕、平滑滚动和会话导出。

**当前为开发预览，尚无正式安装包。** Android 客户端、联网增强尚未实现；连续发言与歌曲修订已接入实验入口，效果仍需用更多样本核对。

## 已有功能

- 麦克风连续收音，粤语 ⇄ 普通话字幕及译音。
- Windows 默认输出设备的声音翻译，适用于浏览器、视频及网课等播放内容。收音期间只显示字幕，停止后可播放译音，避免再次识别自己的声音。
- 处理粤语、普通话和英文识别结果；遇到日语、韩语标签或相关文字会按所选方向重试或拒绝。底层模型本身仍是多语言模型。
- 原文、译文按条配对；最多保留 10,000 条、合计 2,000,000 字符，达到任一上限后移除最早记录。
- 向上滚动时暂停跟随新字幕；可以返回最新位置、复制及手动导出。停止和切换方向会保留当前会话。
- 可选段落修订模式：Qwen3-ASR-1.7B 识别原始音频，同一段发言持续更新原记录；句末复核，较早稳定的前文逐步固定，翻译只处理未确认部分。麦克风和设备声音均可使用。
- 歌曲文件支持最多 10 分钟 / 100 MB 的 MP3、WAV、FLAC、OGG；设置中的人声分离为可选高质量处理，只用于文件，不增加实时收音开销。

字幕只保留在本次运行的内存中，退出即释放；需要留存时请先导出。设备声音输入采集默认输出的混合声音，暂不支持只选择一个应用。

## 开发环境与启动

当前支持 Windows x64、Python **3.12**。首次安装依赖及准备模型需要联网；准备完成后推理使用本地文件。下载需数 GB 空间，请另留依赖和模型解压空间。

在仓库根目录的 PowerShell 中执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[offline,dev]"
.\.venv\Scripts\python.exe experiments\offline-poc\prepare_models.py asr canto hymt2 runtime mandarin vad
.\.venv\Scripts\python.exe -m yuepu_translate
```

也可双击根目录 `Start-YuePu.cmd`。已有 `experiments/offline-poc/.venv` 的本地环境可继续使用旧启动器，不必重新下载模型。源码安装是目前的使用方式，以上命令不会创建 Windows 安装包。

数据目录由 `YUEPU_DATA_DIR` 指定，必须为绝对路径。在源码目录运行时默认使用 `experiments/offline-poc/`，以复用已有模型；独立安装时默认使用 `%LOCALAPPDATA%/YuePuTranslate/`。模型准备和应用必须使用同一个目录，设置环境变量后需重启应用。

```powershell
$env:YUEPU_DATA_DIR = "D:\YuePuData"
```

操作与故障处理见 [Windows 使用说明](docs/windows.md)。依赖锁定的是直接依赖版本，尚未提供完整的传递依赖锁文件；全新机器安装和运行仍需持续验证。

## 项目结构

```text
src/yuepu_translate/          应用包：Qt 窗口、音频引擎、字幕、模型加载
tests/                       不需要模型或音频设备的回归检查
experiments/offline-poc/      模型准备和可选的真实模型诊断；旧启动入口
docs/                        用户及开发说明
.github/                     CI、Issue 和 PR 模板
```

模型、运行时二进制、录音、导出内容、测试输出、环境缓存和内部开发笔记均不纳入 Git。实验脚本不属于稳定 API，也不作为应用运行依赖。

## 本地检查

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m build
```

CI 只运行静态检查、无模型测试和打包，不下载模型、不采集声音。真实模型验证方法及证据边界见 [开发说明](docs/development.md)。

## 模型与限制

默认链路为 SenseVoice-Small INT8 → Hy-MT2-1.8B Q4_K_M → Canto-TTS-Nano / Piper 普通话，使用 Silero VAD 断句。文件来源和固定版本见 [第三方组件说明](THIRD_PARTY.md) 及模型准备脚本。

段落修订需额外准备模型，随后在窗口选择“识别模式 → 段落修订（实验）”：

```powershell
.\.venv\Scripts\python.exe experiments\offline-poc\prepare_models.py song-asr-large
# 可选，仅用于“设置 → 高质量选项 → 人声分离”的歌曲文件处理
.\.venv\Scripts\python.exe experiments\offline-poc\prepare_models.py song-separator
```

收音按钮再次点击会停止采集并确认末尾段落；独立“停止”按钮或 Esc 立即取消未完成处理。字幕会标明暂定、前文已固定或已确认。句末由人声停顿判断，仍可能误判；标点复核不保证歌词正确。歌曲文件处理不自动播报，可完成后手动播报选中译文。

目前使用 CPU 推理；速度随设备和内容变化。对话、歌词、伴奏和混响的效果差异明显，未提供通用准确率、手机延迟或长期运行保证。会话模式文件输入仅支持不超过 15 秒的 WAV，单次文本输入最多 120 字符。段落修订使用最多 30 秒的有界识别上下文，不是模型原生流式识别；已固定的文字不会被后续识别改写，旧音频退出窗口后不再进入识别。人声分离耗时较长。离线保护包含 Python 外部套接字拦截和 llama.cpp 离线参数，尚不能代替完整的操作系统断网审计。

## 参与和授权

欢迎提交可复现的问题和小范围改进，请先阅读 [贡献指南](CONTRIBUTING.md)、[行为准则](CODE_OF_CONDUCT.md) 和 [安全说明](SECURITY.md)。请勿在公开 Issue 上传私人录音、密钥或未获授权的歌曲。

本项目原创源码按 [MIT](LICENSE) 许可，可修改和商用。第三方模型、库和运行时保留各自许可，不能用本项目 MIT 许可替代其授权；发布包含模型的安装包前仍需逐项核对。
