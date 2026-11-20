"""Windows inference files pinned to the prepared, tested model revisions."""

SOURCES = {
    "asr-wenet": "https://huggingface.co/csukuangfj/sherpa-onnx-wenetspeech-yue-u2pp-conformer-ctc-zh-en-cantonese-int8-2025-09-10/resolve/c911764e8227cf372ee60adc75f7f407e5b8c905/",
    "canto": "https://huggingface.co/typangaa/canto-tts-nano/resolve/fe17418a293d9be85685ddf750b0cfef9c88abb4/",
    "hymt2": "https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/a0c709d9fac510f2c807aa3af52872340dc37a4a/",
    "tts-zh": "https://huggingface.co/csukuangfj/vits-melo-tts-zh_en/resolve/a0d5c6a264c0ef92d70d8661d8cc502d79627cd6/",
    "song-asr-large": "https://huggingface.co/ggml-org/Qwen3-ASR-1.7B-GGUF/resolve/36a678687ba7d07a74ca70ccb0e36902e005fb80/",
    "vad": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/",
    "song-separator": "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/",
}

# One row per upstream file: name relative to its folder, byte size and SHA-256.
# fmt: off
FILES = {
    "asr-wenet": (
        ("model.int8.onnx", 134698500, "201bfd9e12ec4ac9ee3b23c5e071d9fa2381a8b21df317e2e08a170d6f1f55d3"),
        ("README.md", 129, "bb7e32790a78c1832c6e8eda7199d70591e9fe3d677be52d40722062a3023d36"),
        ("tokens.txt", 85361, "c7750677a1183606d2fd6f16d792e06e70d9843dba8a0c6e23a9dec78e06977a"),
    ),
    "canto": (
        ("added_tokens.json", 1677, "32eea80bb2cee76ecfb423ab8be32dbdc70c2ee6b319670e212f9be4fab26e98"),
        ("browser_poc_manifest.json", 11740, "db6c56a975ae5b6fa8bc00933cc1eb7046a4d74a00b04c51a7fce0584b5bbfd1"),
        ("MOSS-Audio-Tokenizer-Nano-ONNX/codec_browser_onnx_meta.json", 17036, "3e291c883bb7d11ff2fe8e964e3e495519760358859f35c951254c7741592731"),
        ("MOSS-Audio-Tokenizer-Nano-ONNX/moss_audio_tokenizer_decode_full.onnx", 681902, "0fbbafe3fd4afa2a019af5c5ced204af6e2d1db044fa40f021525d2aee95b4ac"),
        ("MOSS-Audio-Tokenizer-Nano-ONNX/moss_audio_tokenizer_decode_shared.data", 44198912, "e69d52e0f4e84ca27850557ee54face46632d3a5a16c89bd246c7c408466dcad"),
        ("MOSS-Audio-Tokenizer-Nano-ONNX/moss_audio_tokenizer_decode_step.onnx", 351400, "9527c86a29e1837edec1f74db57d5eeaadb3a715af3382703566460afed25855"),
        ("MOSS-Audio-Tokenizer-Nano-ONNX/moss_audio_tokenizer_encode.data", 44507136, "aa751265b2bab2887eac224484546b194875aa7494b607115439b3dc6b228a2c"),
        ("MOSS-Audio-Tokenizer-Nano-ONNX/moss_audio_tokenizer_encode.onnx", 815775, "eadea4a645abdcf98714c7aead122ee2ce7da6e080f9f80b977cd1ca8e19473a"),
        ("MOSS-Audio-Tokenizer-Nano-ONNX/README.md", 4892, "3c7b9e9ef1c8c5e5c829a077a1d32c1f7aea1668f2bf17ead318ff04bf1e6fe4"),
        ("MOSS-TTS-Nano-cantophon-ONNX/moss_tts_decode_step.onnx", 291483, "245846789d1a7186c3087de756c38f698252dbafe47eb73ac243ee9df1292e81"),
        ("MOSS-TTS-Nano-cantophon-ONNX/moss_tts_global_shared.data", 441083904, "6cf65e309adf12f837af995a7f81f6b13ded287af21763df9f9421c1c96c5137"),
        ("MOSS-TTS-Nano-cantophon-ONNX/moss_tts_local_cached_step.onnx", 53685, "a66a3d8946d460b5bd859a1af3fc089819259c3684056bddc6640ffcf804b383"),
        ("MOSS-TTS-Nano-cantophon-ONNX/moss_tts_local_decoder.onnx", 50194, "05afc6a6f2f41981f1f1552fe772125b4dfc2bd3d13822ace45e17066f380480"),
        ("MOSS-TTS-Nano-cantophon-ONNX/moss_tts_local_fixed_sampled_frame.onnx", 471262, "c3108436e014123ad860c17f841b24cf7b9926699a0da7095ff83b2106af2359"),
        ("MOSS-TTS-Nano-cantophon-ONNX/moss_tts_local_shared.data", 230218752, "8467ffced719677e4e2563ac41cadac5b55b20315a7b8c0fc866484c46485822"),
        ("MOSS-TTS-Nano-cantophon-ONNX/moss_tts_prefill.onnx", 283305, "22844a9cd0bd48c61006301d1eb75d6a78085b3e038f405fb990b2994adb78b2"),
        ("MOSS-TTS-Nano-cantophon-ONNX/tokenizer.model", 470897, "c353ee1479b536bf414c1b247f5542b6607fb8ae91320e5af1781fee200fddff"),
        ("MOSS-TTS-Nano-cantophon-ONNX/tts_browser_onnx_meta.json", 4304, "b263ee5d650a6b34e69fea3cc0373ec6838adad8ee5633954faa2af0dd146823"),
        ("README.md", 4149, "8684f5b4e8a00b8b4a64cacdabc432ea6203632d9595baad6fb68d449645fe9e"),
        ("tokenizer.model", 470897, "c353ee1479b536bf414c1b247f5542b6607fb8ae91320e5af1781fee200fddff"),
    ),
    "hymt2": (
        ("Hy-MT2-1.8B-Q4_K_M.gguf", 1133080448, "dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699"),
        ("LICENSE.txt", 11639, "a1d52d448f81c584a47c583e19dfab2d3851c7c84431b07baee093c1113ed114"),
        ("README.md", 15305, "6811073b8b3d20a9a4db959c2b3f36e39e66bdb953cfecbdd8223fc20cc9a05b"),
        ("README_CN.md", 14489, "c67aa57f592eb20f54dbaabcd51a2a13c32e7dd1ae1275a4917f4668debbb412"),
    ),
    "tts-zh": (
        ("date.fst", 59154, "eb8aa079ae3cb81d8f4404992f39d61a0cb990947512b5b8d1e54d1f6980e718"),
        ("dict/hmm_model.utf8", 519739, "f17790586ac86dd048c8adffed052c4bd2b28ed0682972c1275e59040c0589a7"),
        ("dict/idf.utf8", 5998717, "dbd1e03d72b2263cc8d84a4304ed77677eed9e7deaf43a1a5133bbba9733b535"),
        ("dict/jieba.dict.utf8", 5071204, "3043b77068e09c9904f27cad82f12b6ebe9dbdb5aeff3b25e45ab7f9c1122b55"),
        ("dict/pos_dict/char_state_tab.utf8", 327139, "28b7be1dd7369766a51445af4d42e9a2ba4bf374c13be5bc1ca7721e27271dbb"),
        ("dict/pos_dict/prob_emit.utf8", 1687686, "c33c4cb7edf3b3a5947df7209b6e9f267eae1f21335d9e2bd2521ea07105457a"),
        ("dict/pos_dict/prob_start.utf8", 4347, "13623ea0e9300bdb597cb2da28770b7b385d6c0098d66e516083fb01b6bd5d96"),
        ("dict/pos_dict/prob_trans.utf8", 124159, "f22363e2307408293d180c6f9f6b5cb75879d52f722f7764fa2d3d0ae2400236"),
        ("dict/README.md", 683, "8bcc7c2ed7dff082d9a99c09de0bfd72249bf3b5c4298a3af328da40cbd8cfd1"),
        ("dict/stop_words.utf8", 8974, "b788b8a939d2e2fe079abd579ea98f12f9fb84370bfd0dddd81bb9381f7ab42c"),
        ("dict/user.dict.utf8", 49, "495bbf49270408a1234690e1e6a97328f30a482a7a72aa769e8a12e8714b0c62"),
        ("lexicon.txt", 6837671, "7236884b02435ac5d10cf69b4be40a61b45aa676b5300f0e412f185748fee528"),
        ("LICENSE", 1053, "88a50e5a02bbc2a5c2f084dc19da751aa97b1690f5fda76cd8005c8634d1ca70"),
        ("model.int8.onnx", 53517430, "f085f5079e05f039b800aeb542f5253c26a303211b0c6465d0d9387977855a63"),
        ("number.fst", 64482, "743f402181fcfebf76cc2f0546b71fa26476e626fbe4e460fb7b4c3a7a8bd5bd"),
        ("phone.fst", 88630, "1ac2b6fa56b1442320c4de7db08353bab8963a2b57f365eebcdd3a2d3562f8d7"),
        ("README.md", 257, "ae6e44dead53dfdbd5b4a77106226f3118eb910222b46cb5533a3860773fc6c7"),
        ("tokens.txt", 655, "d18664a7e12bd7ea1022ddaf951e534e136815016c5a809d6b64156bffb4369d"),
    ),
    "song-asr-large": (
        ("mmproj-Qwen3-ASR-1.7B-Q8_0.gguf", 355709344, "46c1d533af3f354ceb37ce855dbceff7da7fa7cf1e6a523df3b13440bd164c0d"),
        ("Qwen3-ASR-1.7B-Q8_0.gguf", 2165034944, "58e22d0532d4eacaf034cfac17a6fed159f37c41390c710186783be439d1fc57"),
        ("README.md", 265, "0d9910d9a297a4b92d46094d03e26b948614b6afd429499199c5a449274d2995"),
    ),
    "vad": (
        ("silero_vad.onnx", 643854, "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"),
    ),
    "song-separator": (
        ("Kim_Vocal_2.onnx", 66759214, "ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b"),
    ),
}
# fmt: on
