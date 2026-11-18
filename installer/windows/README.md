# 粤普同传 Windows 本地安装包

有完整安装程序和分卷时，可在干净的一次性 Windows x64 虚拟机中运行 `.\installer\windows\verify_install_in_vm.ps1 -Installer <安装程序路径> -Evidence <日志目录> -DisposableVM`。此检查使用独立安装目录，核对当前用户的卸载登记、开始菜单快捷方式和随包运行环境，最后实际执行卸载并保留日志。

使用 Inno Setup 6 制作包含应用、私有 Python 3.12 运行环境、基础离线模型、pro 复核和文件人声分离模型的 x64 开发预览。此流程只在本地生成文件，不上传、签名、修改系统 Python 或设置全局 PATH。

从仓库根目录、已准备好 `[offline]` 依赖和模型的 Python 3.12 x64 环境执行：

```powershell
python -m unittest discover -s installer/windows/tests -v
python installer/windows/payload.py --output outputs/windows-installer/payload
& 'D:\Applications\Inno Setup 6\ISCC.exe' /DSpanDisks installer/windows/YuePuTranslate.iss
python installer/windows/bundle.py --installer-dir outputs/windows-installer/release `
  --payload outputs/windows-installer/payload --output outputs/windows-installer/YuePuTranslate-Windows-x64-Full.zip
```

`payload.py` 要求输出目录尚不存在，避免混入旧文件。它优先选用当前虚拟环境中的已安装依赖，验证声明的版本及传递依赖，按安装记录收集文件；不复制整个开发环境。应用模块和 Python 原生扩展使用相对路径，`python312._pth` 阻止加载系统／用户的其他包。采集和联网子进程继续使用独立 Python 解释器，避免冻结应用后 `-m` 工作进程失效。

Alpha 2 只收集应用使用的 Qt Core/Gui/Widgets/OpenGL/Svg 和所需平台、图像与样式插件；不整包复制 QML、QtQuick、虚拟键盘或开发工具。Qt、SoXR、libsndfile 及相关 codec 的对应源码、原始构建配方和补丁须作为同版 `Corresponding-Sources.zip` 附件提供；发布方须保持下载可用。许可全文和来源见 `licenses/README.md`。只附 LGPL 文本或上游主页不能代替对应源码提供义务。

私有 Python EXE 使用进程级 UTF-8 `activeCodePage` 清单，避免 SentencePiece／eSpeak 在中文安装路径下打不开资源。只修改包内两个解释器的资源清单，移除因此失效的原厂签名，记录修改前后摘要；不修改系统 Python、系统语言、模型和第三方 Python 库源码，也不提高运行权限。安装配置最低为 Windows 10 1903（18362），尚未证明所有支持版本均可用。

普通话模型已换为 MyShell.ai MIT 许可的 MeloTTS INT8；更新旧环境先运行 `python experiments/offline-poc/prepare_models.py mandarin`，数据位于 `models/tts-zh/`，不自动回退到旧 Huayan 模型。模型仅从显式列出的已准备目录收集，排除候选模型、录音、导出及缓存。脚本生成 `payload-manifest.json` 与显式 `payload-files.iss`；Inno 只读取该文件清单，不会把之后生成的缓存或其他文件带入安装包。构建前应重新核验清单中的 SHA-256。

基础识别改用 Apache-2.0 WenetSpeech-Yue U2++ INT8，旧环境先运行 `python experiments/offline-poc/prepare_models.py asr`，文件位于 `models/asr-wenet/`。当前 MODEL_DIRS 不含 SenseVoice 或旧 Huayan，模型许可检查可通过；许可全文、固定模型卡和证据随安装数据保存到 `docs/licenses/models/`。`--check-licenses` 可在不生成文件的情况下检查许可接线；`--private-development` 仍仅标记本地开发，不授予权利。bundle 拒绝缺少许可记录或记录过期的 payload，但尚不能证明 EXE/BIN 与传入 payload 的编译关系；必须重编并另验实际安装内容，不能仅给旧 BIN 增加外层 ZIP 告知便视为已修复。

完整数据超过 Inno 单 EXE 的大小边界，必须使用 `/DSpanDisks`。每个 BIN 分卷上限为 1,500,000,000 字节，满足 GitHub Release 单附件小于 2 GiB 的限制。安装 EXE 和全部 `Setup-*.bin` 放在同一个文件夹中，直接运行 EXE，无需合并分卷；最终交付 ZIP 同时包含这些文件、使用说明及第三方告知文件。更改暂存路径时需同时设置编译宏 `PayloadDir` 和 `PayloadFileList`。

当前模型许可检查已通过；准备 Release 前仍须重新生成 payload、编译 EXE/BIN 并核验实际安装内容，不要上传旧 BIN。既有安装包不会被源码改动自动更新。源码检查通过不等于常规安装／卸载验收或完整公开发布批准。

安装默认仅作用于当前用户，位置为 `%LOCALAPPDATA%\Programs\YuePuTranslate`；不要求管理员权限。开始菜单快捷方式使用私有 `pythonw.exe -I -B launch.py`，桌面快捷方式由用户主动选择。卸载只按 Inno 登记的文件清单移除程序及模型，不删除用户设置、密钥和手动保存的内容。自定义环境变量 `YUEPU_DATA_DIR` 仍优先，不迁移原源码模型。

实际运行检查使用安装包里的 Python：

```powershell
& '<安装目录>\python\python.exe' -I -B -X utf8 installer/windows/verify_runtime.py `
  --installation '<安装目录>' --evidence outputs/windows-installer/runtime-check
```

检查使用临时用户设置、合成短句及静音生成的音频，覆盖真实双向翻译、译音、轻量和 pro 识别、分离模型加载、界面渲染、非法长输入与真实启动入口。它不会打开麦克风或扬声器，不使用付费云服务；本机检查不等于全新 Windows 虚拟机或所有机型验证。

本次构建已通过 106 项 Windows 回归检查和中文路径下的真实模型／Windows 字体检查。常规安装尝试完成全部文件解压后，当前自动化环境拒绝开始菜单和卸载注册表写入，安装器自动回滚；测试创建的登记项及空目录已清理。该项不能标记为安装／卸载验收通过，需在正常 Windows 桌面环境验证。最终运行证据来自按同一清单重定位的隔离目录，不冒充安装器成功结果。

许可证、包版本及上游来源见 `ThirdPartyNotices.txt`、`licenses/` 和根目录 `THIRD_PARTY.md`。简体中文安装翻译来自 Inno Setup 官方目录链接的上游文件，保留其原始作者信息；SHA-256 为 `e0b0b350e2245f3c5e65586dfe43d574f6e7f06f2261149aba284954b3fc9a8d`。当前安装包未做代码签名，也未完成公开分发授权审计。
