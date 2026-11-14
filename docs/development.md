# 开发与验证

## 应用边界

`src/yuepu_translate` 是运行逻辑的唯一实现位置：

- `desktop_qt.py`：窗口、任务队列、配对字幕和平滑滚动。
- `desktop_theme.py`：深浅主题颜色、Qt 样式、原生调色板及矢量空状态。
- `desktop_engine.py`：识别、翻译、合成、麦克风和 WASAPI 混合声音输入。
- `live_session.py`：默认会话的原文快照识别、独立翻译／播报线程及字幕版本事件。
- `transcript_model.py`：会话内缓存及导出。
- `capture_process.py`、`capture_worker.py`：设备采集、原始 PCM 管道及可限时回收的子进程。
- `paragraphs.py`：段落文字修订、固定前文保护及相邻上下文衔接。
- `translation_state.py`：两种实时模式共用的固定译文缓存、暂定尾部及有界新增文字翻译。
- `enhanced_inference.py`：同一任务内的本地／云端调用选择及首次失败后固定本地的状态。
- `cloud_config.py`、`cloud_dialog.py`：显式启用、配置、当前 Windows 用户加密凭据及异步连接测试。
- `cloud_protocol.py`、`cloud_client.py`、`cloud_worker.py`：百炼有界契约、匿名管道、固定 HTTPS 地址与请求进程回收。
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

自动检查通过不能证明手机运行、真人对话准确率、歌曲识别准确率、完整网络隔离或正式安装包可用。新增模型须使用同一音源比较并人工核对；没有人工参考文本就不报告字符错误率或识别准确率。

界面改动可运行 `.\.venv\Scripts\python.exe experiments\offline-poc\ui_preview.py`。该脚本不加载模型、不采集或播放声音、不发起联网请求；使用明确标注的示例字幕和状态，渲染深浅主题的 1240×850、960×700 窗口、文字输入、错误及联网设置。截图与检查结果保存在根目录 `outputs/ui-review/`，外观偏好隔离到该目录。它验证主题切换、正文对比度、键盘焦点、滚动位置、复制和导出，不代表真实模型或物理设备验证。

## 会话实时字幕

`LiveSession` 复用基础 SenseVoice，使用同一 `RollingAudio` 的短窗口配置：首轮 0.8 秒、更新间隔 0.64 秒、前导 0.32 秒、静音结束阈值 0.65 秒，连续约 8 秒后确认并开始下一条。采集仍通过同一独立进程和 `PlaybackProcessor`；实时段落修订的上下文改为 8 秒、2 秒重叠，独立的段落起点确保连续约 15 秒后归档，不会被上下文检查点重置。

原文识别在会话任务线程执行；Hy-MT2 常驻翻译进程的准备、翻译及已确认译音由独立线程串行处理，不阻塞后续原文。两条队列各保留正在执行的任务、最新一份草稿及最多 3 份等待确认任务；超限明确停止。两种实时模式都使用 `ParagraphRevision` 和 `IncrementalTranslation`：只翻译新增固定短句及暂定尾部，固定前文不再次送入翻译；每次新增输入再切为不超过 96 字的请求。未变化的尾部及恰好升级为固定短句的完整草稿复用译文；会话暂定翻译至多约每 2.5 秒重新生成，固定短句和句末不受此节流影响。

每次原文更新带段号和版本；Qt 仅采用匹配版本的暂定译文。旧版本中已经完成、仍与当前原文一致且只增不减的固定前文可保留，过期尾部及取消前事件均丢弃。新原文不清空整条译文。`TranscriptEntry` 用原文／译文固定前缀长度驱动亮色及浅色显示，文字状态和无障碍描述同时说明状态，复制及导出仍是纯文字。行号使用固定时间查找，布局高度每条字幕保留当前版本，避免历史字幕和修订次数增加后反复扫描、挤出历史高度缓存。取消时等待本次翻译线程退出并回收模型进程，不能遗留线程进入下一会话。只在确认后播报，设备收音始终禁止自动播报。

可用已准备的本地语音样本进行真实模型、Qt 按钮和字幕显示验证：

```powershell
.\.venv\Scripts\python.exe experiments\offline-poc\live_caption_probe.py path\to\speech.wav --source zh --output experiments\offline-poc\outputs\live-caption-zh
# 粤语方向及设备声音入口（仍是本地 PCM 注入，不是真实回采）
.\.venv\Scripts\python.exe experiments\offline-poc\live_caption_probe.py path\to\cantonese.wav --source yue --device --output experiments\offline-poc\outputs\live-caption-yue
# 重复样本并预置历史字幕；改用 --profile paragraph 可检查较重模式
.\.venv\Scripts\python.exe experiments\offline-poc\live_caption_probe.py path\to\cantonese.wav --source yue --device --repeat 6 --history-rows 2000 --output experiments\offline-poc\outputs\live-history
```

该检查按播放速度把 PCM 注入生产采集处理器，通过实际 Qt 收音按钮、任务及字幕模型，使用真实本地识别／翻译并保存首屏、完成截图和计时 JSON。它不访问物理设备、不上传音频；不能代替真实麦克风／WASAPI、播报回声、长时间交流或准确率验证。对照值为旧 `SpeechSegmenter` 首次交出音频片段的时刻，尚未包含旧识别、翻译或排队时间。

## 歌曲评估

歌词评估必须使用独立的人工参考文本，不能把模型转写当作标准答案。
`experiments/offline-poc/song_metrics.py` 提供字符编辑距离及替换、删除、插入计数；
重复识别的内容保留在评分中。调用方须明确记录简繁转换、标点及空白的处理方式。
少量歌曲样本的字符错误率不能作为通用识别准确率；离线运算耗时、输入窗口末端到字幕更新的耗时、
逐字延迟以及句末最终确认耗时应分别报告。

人工歌词、录音和逐字对齐结果仅保留在本地已忽略的 `outputs/` 中。

歌曲模式的实现分别由 `song_stream.py`（有界音频窗口、暂定任务合并和邻接重叠合并）、
`local_inference.py`（仅本机的常驻 ASR / 翻译进程及取消清理）、`song_pipeline.py`（确认状态和文件处理）、
`vocals.py`（可选离线分离）负责。Qt 只负责启动、收音、显示和导出，不维护另一套推理逻辑。
实时识别使用 Silero 人声活动门控，保留 2 秒前导音频，持续约 2 秒未检测到人声后结束段落。
人声检测不是可靠的音乐/人声分类器；它只减少纯伴奏误调用，仍需歌曲实测。
首个暂定快照约在 4 秒，之后约每 2 秒产生一份；最多保留正在执行及最新的待处理草稿。
实时音频上下文最多 8 秒，满窗保留 2 秒重叠进入下一检查点；检查点更新同条记录，连续约 15 秒后另起一条。
检查点和句末优先，最多积压 3 个，超限明确停止。识别线程数最多使用 12（不超过本机逻辑核数），
翻译也最多使用 12 线程；速度须按机器实测，不能从线程数推断延迟。

`paragraphs.py` 是两种实时模式的文字状态唯一实现：关闭后拒绝迟到更新；满 2 秒后，
连续两次一致的完整短句可分批固定，至少留下 8 个字符继续修订；不按任意字数截断尚未结束的词句。重叠上下文可替换尚未固定的错字，
固定前缀始终保留。固定前文的译文缓存，后续只翻译未确认部分；无变化的尾部复用译文。
上下文衔接优先使用最长精确重叠；只有没有精确匹配时才允许等长的小范围字差，
不能通过删除重叠区前的文字扩大匹配。句末没有有效文字时只撤回暂定尾部，保留已固定的原文和译文。
句末人声已经被最近一次识别完整覆盖时复用该识别，否则重新识别；沿用识别标点并补结束标点，只翻译变化部分，
不再调用翻译模型对整段进行额外标点重写。
译音在本段确认后按已缓存的确认片段生成一次；设备收音期间禁止播报。

段落模式滚动 PCM 缓冲约 8 秒，排队的检查点和句末窗口另有数量上限。固定文字并不代表跳过其尚在窗口内的
音频编码：有界上下文仍用于识别衔接，超过窗口的音频才完全退出；不能宣称已有原生流式 KV 缓存。

`capture_worker.py` 独立进程只负责设备和原始 PCM，不加载 NumPy 或推理库；
`capture_process.py` 管理启动、内存管道和退出，并把 PCM 交给同一 `PlaybackProcessor` / 段落门控处理。
启动 12 秒未就绪则报错并回收；先请求协作停止，1 秒未结束则终止本次进程。
管道为长度受限的二进制 PCM 和 JSON 元数据，不使用网络或 pickle，不记录音频文件。
WASAPI 空闲端点在部分驱动上会阻塞 `OpenStream`，因此由轻量独立进程在同一默认输出端点保持完全静音的客户端，
不调节系统音量，停止采集时一并关闭。真实音源未开始播放时也须验证启动，不能只在已有播放时检查。

歌曲文件用 30 秒窗口、4 秒重叠；分离仅作用于文件，使用固定 SHA-256 的 Kim_Vocal_2，
44.1 kHz 双声道、FFT 7680、hop 1024、25% 分离窗口重叠和 1.009 补偿。
该独立 NumPy 适配器与上游完整包尚未逐样本对照，模型再分发授权也不由代码 MIT 许可覆盖。
文件和实时音频共用人声活动检测，避免把纯伴奏直接送入识别；文件相邻窗口只有实际音频重叠时才合并文本。

基础模型准备完成后，额外运行：

```powershell
.\.venv\Scripts\python.exe experiments\offline-poc\prepare_models.py song-asr-large
.\.venv\Scripts\python.exe experiments\offline-poc\prepare_models.py song-separator
```

两个常驻进程仅绑定 `127.0.0.1`，使用临时随机凭据，禁用代理及下载；
音频请求在内存中编码，不写录音或请求日志。停止、取消、超时和加载失败会回收本次进程。
这不是操作系统级网络隔离证明。歌词基准不能输入识别提示；实时窗口方案须单独计分，
不能沿用文件长窗口的错误率。设备回采计时与直接文件送入计时也须区分。

## 联网契约与验证

`SessionInference` 是本地／云端选择的唯一状态持有者，字幕仍复用同一 `ParagraphRevision`。
本地 ASR／翻译进程先就绪并仅在本机预热，再允许发起云端请求；这样首次云端失败后无需临时下载模型。
任何 `CloudError` 都把本任务锁定为本地，取消不触发回退。文本任务只准备翻译进程；
实时与文件任务准备 ASR 和翻译，进程清理仍由原任务负责。

`cloud_worker` 是唯一云端网络出口，使用标准库 HTTPS，不依赖 OpenAI 或百炼 SDK。
主程序不解除 `offline.enable()`。地域及可选业务空间 ID 只用于构造固定服务域名，
不提供任意 URL；禁用代理、重定向和自动重试。凭据和内容只通过匿名管道传入，
不进入命令行或请求日志。输入 JSON 最多 1.4 MB、响应最多 64 KiB，音频须是最多 30 秒的
16 kHz 单声道 PCM16 WAV。正文截断、损坏响应及不支持的文字触发回退，不作为确认结果显示。

请求有 3–30 秒总等待期限。管道收发由受控线程执行；主任务保持可取消，超时／取消终止并回收
请求子进程，因此即使子进程不读 stdin 导致大请求堵塞，UI 任务也能退出。不得把子进程的
套接字超时视为整个任务的取消证明。

`test_cloud_transport.py` 在实际子进程中运行生产请求入口，只把最底层 HTTP 传输重映射到
`127.0.0.1` 的模拟服务；不提供产品可用的“跳过 TLS”或“允许任意地址”配置。
这验证管道、负请求及进程生命周期，不验证真实云模型输出质量。真实窗口验证还须分别记录
真实设备输入、测试 PCM 注入、模拟 API 输出和真实本地模型输出，不能混称云端验收。
有效账户的两种模型权限、真实云端质量和公网延迟，必须由用户在设置中提供凭据后单独核验。

## Git 约定

主分支为 `main`。文件使用 UTF-8；通常 LF 换行，Windows 启动脚本使用 CRLF，由 `.gitattributes` 统一。提交信息见 `CONTRIBUTING.md`。

仓库配置只对本项目生效。内部 `dev-docs/`、旧实验日志、模型及私人输出由 `.gitignore` 保留在本地。连接远端后仍需先审查暂存文件，再提交和推送。
