# 粤普随译 Android 开发预览

独立的 Kotlin/ARM64 客户端，保留仓库内 Windows 版。使用本地 WenetSpeech-Yue U2++ 识别、Hy-MT2 翻译、MeloTTS 普通话，以及手机已安装的离线粤语系统语音。手机性能、真实收音和音质须以真机验收为准。

## 当前能力

- 粤语 ⇄ 普通话方向切换；麦克风收音、滚动原文、粗略译文、句末确认和目标语言播报。
- “标准／灵敏”两档，默认标准；标准用于嘈杂环境，灵敏用于手机外放与轻声。背景人声仍可能被识别，不能锁定指定说话人。
- 自动播报可关闭，已确认字幕可点按重播。自动播报期间暂停收音，并保留短暂回声缓冲。
- 短句输入、系统文件选择器导入模型、手动导出 UTF-8 字幕。字幕只在本次 Activity 内存保留，上限 200 条／200,000 字符。
- 首次导入和每次加载均校验固定模型摘要；模型位于应用私有目录。导入失败保留旧模型，进程在切换中断时恢复上次安装。
- 应用只申请麦克风权限，不申请网络或广泛存储权限。离开应用会停止处理；不支持后台／锁屏收音或其他应用内部音频。

本阶段没有接入 Windows pro 的大模型复核、歌曲文件、人声分离或云服务。不要根据 APK 构建成功推断这些功能可用。

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
2. 点击“导入模型包”，选择 ZIP。完整校验和复制完成后点击“加载模型”。首次校验与预热可能需要等待，状态栏会提示当前步骤。
3. 选择方向和收音档，点击“开始收音”后主动允许麦克风。手机外放测试用灵敏档，嘈杂环境先用标准档。
4. “结束收音”会处理末尾；“停止处理”立即取消并保留已有字幕。可关闭自动播报，先观察识别和译文。
5. 飞行模式下分别验证两个方向。真人样例、延迟、发热和背景干扰需另行记录；合成音频测试不代表真人准确率。

离开应用会停止处理。退出或系统回收进程会丢失未导出字幕；模型保留在应用私有存储，卸载会删除。模型包的源 ZIP 由用户自行管理。

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
