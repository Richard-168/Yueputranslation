# 粤普随译 Android 开发预览

独立的 Kotlin/ARM64 客户端。使用本地 WenetSpeech-Yue U2++ 识别、Hy-MT2 翻译、MeloTTS 普通话，以及手机已安装的离线粤语系统语音。

## 当前能力

- 文字翻译与前台麦克风收音共用底部输入区。翻译方向、收音选项和设置从底部弹出。收音提供滚动原文、粗略译文、句末确认和译音播报。
- 手机上通过顶部“会话”查看历史，宽窗口显示常驻会话栏。手机字幕上下排列，更宽的窗口将原文和译文并排展示。“设置”可选深色、浅色或跟随系统。
- 会话自动保存在应用的本机私有空间，保存原文、译文及显示所需信息。每个会话最多保留 200 条字幕和 200,000 字符。可继续旧会话、确认清空或单独导出 UTF-8 文本。
- 收音灵敏度默认“标准”，适合嘈杂环境。“灵敏”适合手机外放与轻声。自动播报可关闭，已确认字幕可点按重播。自动播报期间暂停收音，并保留短暂回声缓冲。
- 通过系统文件选择器导入或替换离线模型包。首次导入和每次加载均校验固定模型摘要，导入失败时保留旧模型。

Android 的翻译输入限于前台麦克风和文字。离开应用时停止处理，应用权限仅包含麦克风。系统音频翻译、歌曲处理、pro 大模型复核和联网增强见 Windows 版。

布局参考了 21st 上的手机会话列表、底部弹层和紧凑的文字与语音输入区。[Manoj Chat Template](https://21st.dev/@rayimanoj8/components/chat-template/whatsapp-mock) · [Animated Drawer](https://21st.dev/@arihantcodes_1f7b8c4d/components/animated-drawer) · [Agent Dock](https://21st.dev/@dqnamo/components/agent-dock) · [v0 AI Chat](https://21st.dev/@kokonutd/components/v0-ai-chat)

## 构建

要求 JDK 21、Android SDK Platform 35、Build Tools 35.0.0、NDK 27.2.12479018、CMake 3.22.1、Python 3.12。AGP 8.9.2、Kotlin 2.1.20、Gradle Wrapper 8.11.1 已固定；最低 Android 8.0，首批仅 ARM64。

在仓库根目录运行：

```powershell
python android/tools/prepare_dependencies.py
python android/tools/prepare_models.py
```

依赖脚本下载固定版本并校验摘要；模型脚本复用可用的 Windows ASR／MT／VAD 文件，准备 MeloTTS，在 `outputs/android-models/` 生成 ZIP，并更新 APK 校验清单。ZIP 不包含 SenseVoice 或旧粤语音色权重。所有权重和依赖缓存均被 Git 忽略。准备模型和安装系统语音包需要提前联网，运行时只选择离线粤语音色。

用 Android Studio 打开 `android/`，或在 `android/local.properties` 指定本机 `sdk.dir`。CMake 如不在 SDK 中，可额外指定 `cmake.dir`。这些路径不纳入 Git。

```powershell
cd android
.\gradlew.bat :core:test :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
```

默认使用官方 Maven 仓库。官方仓库不可达时可显式添加 `-PyuepuMirror=true` 使用已配置的阿里云镜像；不会切换应用推理路径。Wrapper 校验 Gradle 分发包 SHA-256。

APK：`android/app/build/outputs/apk/debug/app-debug.apk`。模型包：`outputs/android-models/yuepu-android-models-dev.zip`（约 1.25 GiB）。两者须来自同一份新版模型清单；旧包无法导入。APK 不含模型，首次使用还需安装离线粤语语音。

## 手机试用

1. 安装调试 APK，将模型 ZIP 复制到手机可选择的位置，至少预留约 4 GB 空闲空间；替换旧模型时另需约 1.5 GB。
   在系统“文字转语音”设置中，选择合法安装的语音引擎，安装粤语或香港中文的离线语音数据。具体设置位置依手机和引擎而异；只有联网音色、尚未安装数据或只有普通话音色时，应用不会将其当作离线粤语。
2. 在欢迎页或“设置”中导入模型 ZIP。完整校验和复制完成后，首次翻译文字或收音会自动加载模型并继续。也可在“设置”选择“预加载模型”。
3. 在输入区选择方向，输入短句后点击“翻译”，或者点击“开始收音”并允许麦克风权限。嘈杂环境先用标准档，手机外放测试可在“收音选项”选灵敏档。
4. “结束收音”会处理末尾。“取消任务”可立即停止处理并保留已有字幕。可关闭自动播报，先观察识别和译文。
5. 从“会话”打开历史记录，或点“新会话”开始另一组翻译。需要独立文件时点“导出”。
6. 在飞行模式下分别验证两个方向。真机验收时记录真人样例、延迟、发热和背景干扰。

重开应用后可从会话历史找回已保存的字幕。模型和历史存放在应用私有空间，卸载时由系统删除。导出的文本和模型包源 ZIP 由用户在所选位置管理。

## 真机开发检查

先在手机允许 USB 调试并确认 `adb devices` 为 `device`，再安装上述 APK。不要用 `adb -g` 自动授予麦克风权限。模型可以通过界面导入，随后运行：

```powershell
adb install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w org.yuepu.translate.test/androidx.test.runner.AndroidJUnitRunner
```

`OfflineRuntimeTest` 需要新版模型和手机已安装的离线粤语音色，使用真实 ARM64 库及系统语音服务完成双向合成、识别、翻译，报告耗时，并检查取消、缺模型和权限清单；不启用麦克风或扬声器。缺模型或离线粤语音色时明确失败。首次检验必须在飞行模式下运行并核对手机语音引擎行为；应用自身不申请网络权限不等于已审计独立语音服务的全部实现。它不能替代真人收音、外放、延迟、发热与长时间运行验收。

## 模型与许可

手机播报音色不同于 Windows。固定来源和许可边界见 [第三方说明](../THIRD_PARTY.md)；APK 自带 `assets/THIRD_PARTY.txt` 和依赖许可。

当前模型包只含已核对许可的 WenetSpeech-Yue U2++、Hy-MT2、MeloTTS、Silero 及许可材料。SenseVoice 和原粤语 VITS 已退出，历史未决记录保留；系统粤语语音包由用户自行合法安装，应用不复制或再分发。`python tools/model_licenses.py android` 只检查模型许可条件，不代表整个 APK 已获发布批准。本阶段没有上传应用商店；旧 APK／模型 ZIP 不会被源码修改自动修复。
