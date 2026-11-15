# Windows 二进制组件许可

模型许可由仓库 `licenses/models/registry.json` 管理；本目录补充原生库和 Python wheel 中缺失或不完整的许可。安装数据保留各发行包自带的版权、LICENSE 和 NOTICE，并加上本目录材料。

- Qt/PySide6/Shiboken 6.8.3：采用 LGPLv3。只分发 QtBase 的 Core/Gui/Widgets/OpenGL 与 QtSvg 及所需插件，不分发 QML、虚拟键盘、PDF 或 Designer。QtBase、QtSvg、pyside-setup 的官方 6.8.3 源码与重新构建/替换说明，必须随同版 Release 的 Corresponding-Sources.zip 提供。Qt 第三方版权与许可见对应 ThirdPartyNotices。
- Python-SoXR 1.0.0 / libsoxr 0.1.3-14-ga66f3ee：LGPL-2.1-or-later；PyPI 1.0.0 sdist 包含 libsoxr 源码与构建配置。保留原有许可证，并提供完整 sdist。
- SoundFile 0.14.0：Python 代码为 BSD-3-Clause；随 wheel 的 libsndfile 1.2.2 原生 DLL 包含 LAME 3.100、mpg123 1.32.9、FLAC 1.4.3、Ogg 1.3.5、Vorbis 1.3.7、Opus 1.5.2。对应源码、vcpkg 2024.12.16 配方和补丁与自定义 triplet 必须提供。`libsndfile-codecs-ThirdPartyNotices.txt` 保留各组件自身条件，不能统一改为 BSD。用户可替换 `_soundfile_data/libsndfile_x64.dll`。
- sherpa-onnx 2.0.1：Apache-2.0；其官方 PR #4055 已移除 eSpeak-NG/piper-phonemize。本版原生 core 的 ONNX Runtime 为 1.28.2，额外附该版本 MIT 与 ThirdPartyNotices；独立 Python ONNX Runtime 1.31.1 的原告知仍保存在其目录。
- FlatBuffers 25.12.19：补入官方固定 tag 的 Apache-2.0 全文；该 Python wheel 未自带 LICENSE。
- SentencePiece 0.2.3：补入官方 Apache-2.0、darts-clone、libsais、rapidhash（BSD-2-Clause）等告知；按固定版本 CMake 指定的 Abseil 20260817.0、Protobuf v36.2 和 utf8_range 保留各自许可。
- tqdm 4.70.1：其原始 LICENCE 和 Python 源码随包保存，另补 MPL 2.0 全文；未修改该组件代码。

来源均为固定上游版本或上游官方源码归档。Release 的源码清单记录下载地址与 SHA-256；libsndfile codec 源码另核验原始 vcpkg 配方的 SHA-512。mpg123 的 archive/patchset 摘要 `66150af195` 与随包 DLL 的构建目录一致。对应源码提供、告知保留和允许替换库是实际分发条件；目录中存在许可文件不代表整个应用自动满足所有条件。

上游：

- https://download.qt.io/archive/qt/6.8/6.8.3/submodules/
- https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/
- https://github.com/bastibe/python-soundfile/tree/0.14.0
- https://github.com/bastibe/libsndfile-binaries/tree/a3e6f9769d0c7e91d2d036cf0fdbe5b4bbf18b87
- https://github.com/microsoft/vcpkg/tree/2024.12.16/ports/libsndfile
- https://github.com/dofuuz/python-soxr/tree/v1.0.0
- https://github.com/k2-fsa/sherpa-onnx/pull/4055
- https://github.com/microsoft/onnxruntime/tree/v1.28.2
- https://github.com/google/flatbuffers/tree/v25.12.19
- https://github.com/google/sentencepiece/tree/v0.2.3
