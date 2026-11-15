package org.yuepu.translate.engine

import android.content.Context
import com.k2fsa.sherpa.onnx.*
import java.io.File
import java.util.concurrent.CancellationException
import java.util.concurrent.atomic.AtomicBoolean
import org.yuepu.translate.core.Direction

internal class OfflineEngine(private val root: File, private val context: Context) : AutoCloseable {
    private var recognizer: OfflineRecognizer? = null
    private var recognitionDirection: Direction? = null
    private var mandarin: OfflineTts? = null
    private var cantonese: SystemCantoneseTts? = null
    @Volatile private var translator = 0L
    private val unsupported = Regex("""[\u3040-\u30ff\uac00-\ud7af]""")

    private fun path(relative: String) = File(root, relative).absolutePath
    private fun check(cancelled: AtomicBoolean) {
        if (cancelled.get()) throw CancellationException("已取消")
    }

    fun load(direction: Direction, cancelled: AtomicBoolean, status: (String) -> Unit) {
        check(cancelled)
        status("正在加载离线识别…")
        setDirection(direction)
        check(cancelled)
        status("正在加载本地翻译…")
        translator = NativeTranslator.create(path("translation/model.gguf"), 4)
        check(cancelled)
        status("正在预热本地翻译…")
        NativeTranslator.translate(translator, "你好。", false)
        check(cancelled)
        status("正在加载普通话译音…")
        mandarin = OfflineTts(config = OfflineTtsConfig(
            model = OfflineTtsModelConfig(vits = OfflineTtsVitsModelConfig(
                model = path("tts-zh/model.int8.onnx"), tokens = path("tts-zh/tokens.txt"),
                lexicon = path("tts-zh/lexicon.txt"), dictDir = path("tts-zh/dict"),
            ), numThreads = 2),
            ruleFsts = listOf("date.fst", "number.fst", "phone.fst").joinToString(",") { path("tts-zh/$it") },
        ))
        check(cancelled)
        status("正在检查手机离线粤语语音…")
        cantonese = SystemCantoneseTts(context)
        checkNotNull(cantonese).load(cancelled)
        check(cancelled)
    }

    // Called only while idle, after previous capture and recognition threads joined.
    fun setDirection(direction: Direction) {
        if (recognitionDirection == direction && recognizer != null) return
        recognizer?.release()
        recognizer = null
        recognitionDirection = null
        recognizer = OfflineRecognizer(config = OfflineRecognizerConfig(
            featConfig = FeatureConfig(sampleRate = 16000, featureDim = 80),
            modelConfig = OfflineModelConfig(
                wenetCtc = OfflineWenetCtcModelConfig(model = path("asr/model.int8.onnx")),
                tokens = path("asr/tokens.txt"), numThreads = 2, provider = "cpu",
            ),
        ))
        recognitionDirection = direction
    }

    fun recognize(samples: FloatArray, cancelled: AtomicBoolean): String {
        check(cancelled)
        require(samples.isNotEmpty() && samples.size <= 8 * 16000 && samples.all { it.isFinite() })
        val model = checkNotNull(recognizer)
        val stream = model.createStream()
        try {
            stream.acceptWaveform(samples, 16000)
            model.decode(stream)
            check(cancelled)
            val result = model.getResult(stream)
            val text = result.text.trim()
            if (!text.any { it.isLetterOrDigit() } || unsupported.containsMatchIn(text)) return ""
            require(text.length <= 240) { "本段识别内容过长，请缩短连续发言。" }
            return text
        } finally { stream.release() }
    }

    fun resetTranslation() { NativeTranslator.reset(translator) }

    fun translate(text: String, direction: Direction, cancelled: AtomicBoolean): String {
        check(cancelled)
        val result = NativeTranslator.translate(translator, text, direction.target == "zh").trim()
        check(cancelled)
        require(result.any { it.isLetterOrDigit() } && !unsupported.containsMatchIn(result)) { "未生成有效的粤普译文。" }
        return result
    }

    fun synthesize(text: String, target: String, cancelled: AtomicBoolean, audio: (FloatArray, Int) -> Unit) {
        check(cancelled)
        require(target in setOf("zh", "yue"))
        if (target == "yue") {
            checkNotNull(cantonese).synthesize(text, cancelled, audio)
            return
        }
        val model = checkNotNull(mandarin)
        var emitted = 0
        model.generateWithConfigAndCallback(text, GenerationConfig(sid = 0, speed = 1f)) { samples ->
            if (cancelled.get()) 0 else {
                audio(samples, model.sampleRate())
                emitted += samples.size
                if (cancelled.get()) 0 else 1
            }
        }
        check(cancelled)
        kotlin.check(emitted > 0) { "未生成有效译音。" }
    }

    fun cancel() { cantonese?.cancel(); if (translator != 0L) NativeTranslator.cancel(translator) }

    override fun close() {
        cancel()
        // The controller joins all owners before calling this method.
        recognizer?.release(); recognizer = null
        recognitionDirection = null
        mandarin?.release(); mandarin = null
        cantonese?.close(); cantonese = null
        if (translator != 0L) NativeTranslator.destroy(translator)
        translator = 0
    }
}
