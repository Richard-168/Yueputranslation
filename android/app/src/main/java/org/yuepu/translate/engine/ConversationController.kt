package org.yuepu.translate.engine

import android.content.Context
import java.io.InputStream
import java.util.concurrent.CancellationException
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicLong
import org.yuepu.translate.core.*

internal sealed class SessionEvent {
    data class State(val busy: Boolean, val listening: Boolean, val ready: Boolean, val text: String) : SessionEvent()
    data class Source(val epoch: Long, val block: Long, val version: Long, val text: String, val final: Boolean) : SessionEvent()
    data class Target(val epoch: Long, val block: Long, val version: Long, val text: String, val preview: Boolean) : SessionEvent()
    data class Level(val value: Int) : SessionEvent()
    data class Error(val text: String) : SessionEvent()
    data class Finished(val epoch: Long) : SessionEvent()
}

private data class TranslationJob(val epoch: Long, val block: Long, val version: Long, val text: String, val final: Boolean)
private class SessionFailure(val failure: Exception) : RuntimeException(failure)

internal class ConversationController(
    context: Context,
    val models: AppModels,
    private val emit: (SessionEvent) -> Unit,
) : AutoCloseable {
    private val context = context.applicationContext
    private val control = Executors.newSingleThreadExecutor { Thread(it, "yuepu-control") }
    private val closed = AtomicBoolean(false)
    private val playbackUntil = AtomicLong(0)
    @Volatile private var cancelled = AtomicBoolean(false)
    @Volatile private var engine: OfflineEngine? = null
    @Volatile private var capture: AudioCapture? = null
    @Volatile private var player: SpeechPlayer? = null
    @Volatile private var audioQueue: BoundedMailbox<AudioWindow>? = null
    @Volatile private var translationQueue: BoundedMailbox<TranslationJob>? = null
    @Volatile var busy = false; private set
    @Volatile var listening = false; private set
    @Volatile var ready = false; private set

    private fun state(text: String) = emit(SessionEvent.State(busy, listening, ready, text))
    private fun check(flag: AtomicBoolean) { if (flag.get()) throw CancellationException() }

    @Synchronized private fun launch(text: String, action: (AtomicBoolean) -> Unit) {
        kotlin.check(!closed.get() && !busy) { "请等待当前处理结束。" }
        busy = true
        val flag = AtomicBoolean(false)
        cancelled = flag
        state(text)
        control.execute {
            var errorMessage: String? = null
            try { action(flag) }
            catch (_: CancellationException) { state("已取消，已有字幕保留。") }
            catch (error: Exception) {
                if (!flag.get() || error is SessionFailure) {
                    errorMessage = friendly(if (error is SessionFailure) error.failure else error)
                    emit(SessionEvent.Error(errorMessage!!))
                }
            } finally {
                capture?.stop(); capture?.join(); capture = null
                player?.close(); player = null
                audioQueue = null; translationQueue = null
                listening = false; busy = false
                state(errorMessage ?: if (flag.get()) "已停止，已有字幕保留。" else if (ready) "本地模型已就绪。" else "请导入模型并加载。")
            }
        }
    }

    fun importPack(input: () -> InputStream) = launch("正在导入并校验模型…") { flag ->
        ready = false
        engine?.close(); engine = null
        var last = 0L
        input().use { stream ->
            models.importer.install(stream, { flag.get() }) { bytes ->
                if (System.nanoTime() - last > 200_000_000L) {
                    state("正在校验模型 ${(bytes * 100 / models.bytes).coerceAtMost(100)}%…")
                    last = System.nanoTime()
                }
            }
        }
        state("模型导入完成，请加载离线模型。")
    }

    fun load(direction: Direction) = launch("正在校验离线模型…") { flag ->
        ready = false
        engine?.close(); engine = null
        models.importer.verify { flag.get() }
        val loaded = OfflineEngine(models.root)
        engine = loaded
        try {
            loaded.load(direction, flag, ::state)
            check(flag)
            ready = true
        } catch (error: Exception) {
            loaded.close(); engine = null
            throw error
        }
    }

    fun start(epoch: Long, direction: Direction, sensitivity: Sensitivity, speak: Boolean) =
        launch("正在准备收音…") { flag ->
            val local = checkNotNull(engine) { "请先加载离线模型。" }
            kotlin.check(ready)
            local.setDirection(direction)
            local.resetTranslation()
            check(flag)
            val windows = BoundedMailbox<AudioWindow>()
            val translations = BoundedMailbox<TranslationJob>()
            audioQueue = windows; translationQueue = translations
            val output = SpeechPlayer().also { player = it }
            val failure = AtomicReference<Exception?>(null)
            fun fail(error: Exception) {
                failure.compareAndSet(null, error)
                flag.set(true)
                capture?.stop(); local.cancel(); output.stop()
                windows.cancel(); translations.cancel()
            }
            val translate = Thread({
                var previousText = ""
                var previousTarget = ""
                try {
                    while (true) {
                        val job = translations.take { flag.get() } ?: break
                        check(flag)
                        val target = if (job.text == previousText) previousTarget
                            else local.translate(job.text, direction, flag)
                        previousText = job.text; previousTarget = target
                        emit(SessionEvent.Target(job.epoch, job.block, job.version, target, !job.final))
                        if (job.final && speak) {
                            playbackUntil.set(Long.MAX_VALUE)
                            try {
                                local.synthesize(target, direction.target, flag) { samples, rate -> output.write(samples, rate, flag) }
                                output.drain(flag)
                            } finally { playbackUntil.set(System.nanoTime() + 350_000_000L) }
                        }
                    }
                } catch (error: Exception) { if (!flag.get()) fail(error) }
            }, "yuepu-translation")
            val recognition = Thread({
                var block = -1L
                var previousText = ""
                var cachedText = ""
                var coveredEnd = -1L
                var previewAt = 0L
                try {
                    while (true) {
                        val window = windows.take { flag.get() } ?: break
                        check(flag)
                        if (window.block != block) {
                            block = window.block; previousText = ""; cachedText = ""
                            coveredEnd = -1; previewAt = 0
                        }
                        var text = if (window.final && coveredEnd >= window.voiceEnd && cachedText.isNotBlank()) cachedText
                            else local.recognize(window.samples, flag).also { cachedText = it; coveredEnd = window.end }
                        if (text.isBlank()) continue
                        if (window.final && text.last() !in "。！？.!?") text += "。"
                        if (!window.final && text == previousText) continue
                        previousText = text
                        emit(SessionEvent.Source(epoch, block, window.version, text, window.final))
                        val now = System.nanoTime()
                        if (window.final || now - previewAt >= 2_500_000_000L) {
                            translations.put(TranslationJob(epoch, block, window.version, text, window.final), window.final)
                            previewAt = now
                        }
                    }
                } catch (error: Exception) { if (!flag.get()) fail(error) }
                finally { translations.finish() }
            }, "yuepu-recognition")
            try {
                translate.start(); recognition.start()
                val input = AudioCapture(context, models.root, sensitivity, flag,
                    { windows.put(it, it.final) }, { emit(SessionEvent.Level(it)) },
                    { windows.finish() }, ::fail, { System.nanoTime() < playbackUntil.get() })
                capture = input
                input.start()
                listening = true
                state("正在收音 · ${sensitivity.label} · ${direction.label}")
                input.join()
                listening = false
                state("正在确认末尾并完成翻译…")
            } finally {
                capture?.stop(); capture?.join()
                windows.finish()
                recognition.join()
                translations.finish()
                translate.join()
            }
            failure.get()?.let { throw SessionFailure(it) }
            check(flag)
            emit(SessionEvent.Finished(epoch))
        }

    fun text(epoch: Long, text: String, direction: Direction, speak: Boolean) = launch("正在离线翻译…") { flag ->
        require(text.isNotBlank() && text.length <= 240) { "请输入不超过 240 字的短句。" }
        val local = checkNotNull(engine) { "请先加载离线模型。" }
        local.resetTranslation()
        emit(SessionEvent.Source(epoch, 0, 1, text, true))
        val target = local.translate(text, direction, flag)
        emit(SessionEvent.Target(epoch, 0, 1, target, false))
        if (speak) {
            val output = SpeechPlayer().also { player = it }
            local.synthesize(target, direction.target, flag) { samples, rate -> output.write(samples, rate, flag) }
            output.drain(flag)
        }
        emit(SessionEvent.Finished(epoch))
    }

    fun replay(text: String, target: String) = launch("正在生成译音…") { flag ->
        val local = checkNotNull(engine)
        val output = SpeechPlayer().also { player = it }
        local.synthesize(text, target, flag) { samples, rate -> output.write(samples, rate, flag) }
        output.drain(flag)
    }

    fun finishCapture() { capture?.stop(); listening = false; state("正在确认末尾…") }

    fun cancel() {
        cancelled.set(true)
        capture?.stop(); engine?.cancel(); player?.stop()
        audioQueue?.cancel(); translationQueue?.cancel()
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        cancel()
        control.execute { engine?.close(); engine = null; ready = false }
        control.shutdown()
    }

    private fun friendly(error: Exception): String = when {
        error.message?.contains("timed out") == true -> "本句翻译超时，请缩短发言后重试。"
        error.message?.contains("could not") == true -> "本地模型加载失败，请检查模型包和手机可用内存。"
        error is SecurityException -> "没有麦克风或所选文件的访问权限，请重新授权。"
        error.message?.any { it in '\u4e00'..'\u9fff' } == true -> error.message!!
        else -> "处理未完成，请停止后重试；必要时重新加载模型。"
    }
}
