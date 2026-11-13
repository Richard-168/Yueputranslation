# 开发与验证

## 应用边界

`src/yuepu_translate` 是运行逻辑的唯一实现位置：

- `desktop_qt.py`：窗口、任务队列、配对字幕和平滑滚动。
- `desktop_engine.py`：识别、翻译、合成、麦克风和 WASAPI 混合声音输入。
- `transcript_model.py`：会话内缓存及导出。
- `model_runtime.py`、`numbers.py`、`offline.py`、`paths.py`：本地模型、明确指定的数字读音、Python 网络限制和数据目录。

`experiments/offline-poc` 保留模型准备及诊断脚本。三个旧应用模块仅转发到应用包，供原启动器及已有验证脚本使用，不能再向这些入口添加实现。

## 检查分层

README 中的 `unittest` 检查不下载模型、不打开麦克风或扬声器，覆盖字幕保留、容量与导出、数字读音、数据目录和 CLI 参数边界。格式检查与 wheel 构建也不需要模型。

需要真实模型的验证是单独的本地步骤。先安装 `.[offline,dev,diagnostics]`、准备模型，然后在根目录运行：

```powershell
.\.venv\Scripts\python.exe experiments\offline-poc\desktop_smoke.py engine
.\.venv\Scripts\python.exe experiments\offline-poc\desktop_smoke.py playback
.\.venv\Scripts\python.exe experiments\offline-poc\qt_smoke.py
```

这些脚本默认读取实验目录下的模型，验证时不要另设 `YUEPU_DATA_DIR`。Qt 检查使用离屏窗口及静音输出；playback 检查主要验证重采样、分段和真实模型链路，不能代替在播放软件中实际采集。旧 Tk `ui` 检查仅保留作对照。

输出在本地 `experiments/offline-poc/outputs/`，可能包含音频、字幕和机器信息，不进入 Git。`verify_quality.py` 依赖先前的本地输出，不是干净克隆可直接运行的测试。

自动检查通过不能证明手机运行、真人对话准确率、歌曲识别准确率、完整网络隔离或正式安装包可用。新增模型须使用同一音源比较并人工核对；没有逐字标注就不报告准确率。

## Git 约定

主分支为 `main`。文件使用 UTF-8；通常 LF 换行，Windows 启动脚本使用 CRLF，由 `.gitattributes` 统一。提交信息见 `CONTRIBUTING.md`。

仓库配置只对本项目生效。内部 `dev-docs/`、旧实验日志、模型及私人输出由 `.gitignore` 保留在本地。连接远端后仍需先审查暂存文件，再提交和推送。
