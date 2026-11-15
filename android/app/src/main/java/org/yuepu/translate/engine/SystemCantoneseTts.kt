package org.yuepu.translate.engine

import android.content.Context
import android.os.Bundle
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.io.File
import java.util.UUID
import java.util.concurrent.CancellationException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import org.yuepu.translate.core.LocalSpeechVoice
import org.yuepu.translate.core.OfflineCantoneseVoice
import org.yuepu.translate.core.PcmWave

/** Uses an installed offline Cantonese voice; never downloads or bundles voice weights. */
internal class SystemCantoneseTts(private val context: Context) : AutoCloseable {
    private val initialized = CountDownLatch(1)
    private val initStatus = AtomicInteger(TextToSpeech.ERROR)
    private val tts = TextToSpeech(context.applicationContext) { status ->
        initStatus.set(status); initialized.countDown()
    }
    private var voiceName: String? = null

    private fun waitFor(latch: CountDownLatch, seconds: Int, cancelled: AtomicBoolean) {
        check(Looper.myLooper() != Looper.getMainLooper()) { "语音生成必须在后台运行。" }
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(seconds.toLong())
        while (!latch.await(50, TimeUnit.MILLISECONDS)) {
            if (cancelled.get()) throw CancellationException("已取消译音")
            check(System.nanoTime() < deadline) { "手机离线语音未响应，请检查系统文字转语音设置。" }
        }
        if (cancelled.get()) throw CancellationException("已取消译音")
    }

    fun load(cancelled: AtomicBoolean) {
        waitFor(initialized, 15, cancelled)
        check(initStatus.get() == TextToSpeech.SUCCESS) { "无法启动手机语音引擎，请检查系统文字转语音设置。" }
        val voices = tts.voices.orEmpty().associateBy { it.name }
        val choice = OfflineCantoneseVoice.select(voices.values.map {
            LocalSpeechVoice(it.name, it.locale.language, it.locale.country,
                it.isNetworkConnectionRequired,
                !it.features.orEmpty().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED), it.quality)
        }) ?: error("手机尚未安装离线粤语语音。请在系统“文字转语音”设置中安装粤语／香港中文离线语音包，再返回加载。")
        check(tts.setVoice(voices.getValue(choice.name)) == TextToSpeech.SUCCESS) { "无法选择手机离线粤语音色。" }
        voiceName = choice.name
        check(tts.voice?.name == voiceName && tts.voice?.isNetworkConnectionRequired == false) {
            "手机没有启用离线粤语音色，不会切换到联网播报。"
        }
    }

    fun synthesize(text: String, cancelled: AtomicBoolean, emit: (FloatArray, Int) -> Unit) {
        require(text.isNotBlank() && text.length <= minOf(240, TextToSpeech.getMaxSpeechInputLength()))
        if (cancelled.get()) throw CancellationException("已取消译音")
        check(voiceName != null && tts.voice?.name == voiceName && tts.voice?.isNetworkConnectionRequired == false) {
            "离线粤语音色已不可用，请重新加载；不会改用联网播报。"
        }
        val id = UUID.randomUUID().toString()
        val done = CountDownLatch(1)
        val error = AtomicReference<String?>(null)
        val file = File.createTempFile("yuepu-tts-", ".wav", context.cacheDir)
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) { }
            override fun onDone(utteranceId: String?) { if (utteranceId == id) done.countDown() }
            @Deprecated("Legacy engine callback")
            override fun onError(utteranceId: String?) {
                if (utteranceId == id) { error.set("离线粤语生成失败，请检查手机语音包。"); done.countDown() }
            }
            override fun onError(utteranceId: String?, errorCode: Int) { onError(utteranceId) }
            override fun onStop(utteranceId: String?, interrupted: Boolean) {
                if (utteranceId == id) { error.set("离线粤语生成已停止。"); done.countDown() }
            }
        })
        try {
            check(tts.synthesizeToFile(text, Bundle(), file, id) == TextToSpeech.SUCCESS) { "无法提交离线粤语生成。" }
            waitFor(done, 30, cancelled)
            error.get()?.let { error(it) }
            check(file.length() in 44..(16L * 1024 * 1024)) { "手机离线语音没有生成有效音频。" }
            val pcm = PcmWave.decode(file.readBytes())
            check(pcm.samples.any { kotlin.math.abs(it) > .00001f }) { "手机离线语音只生成了静音，请检查语音包。" }
            for (start in pcm.samples.indices step 2048) {
                if (cancelled.get()) throw CancellationException("已取消译音")
                emit(pcm.samples.copyOfRange(start, minOf(start + 2048, pcm.samples.size)), pcm.sampleRate)
            }
        } finally {
            tts.stop()
            tts.setOnUtteranceProgressListener(null)
            file.delete()
        }
    }

    fun cancel() { tts.stop() }
    override fun close() { tts.stop(); tts.shutdown() }
}
