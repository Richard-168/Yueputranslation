package org.yuepu.translate.engine

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import com.k2fsa.sherpa.onnx.SileroVadModelConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import org.yuepu.translate.core.AudioWindow
import org.yuepu.translate.core.LiveSegmenter
import org.yuepu.translate.core.Sensitivity
import kotlin.math.sqrt

internal class AudioCapture(
    private val context: Context,
    private val modelRoot: File,
    private val sensitivity: Sensitivity,
    private val cancelled: AtomicBoolean,
    private val emit: (AudioWindow) -> Unit,
    private val level: (Int) -> Unit,
    private val started: () -> Unit,
    private val ended: () -> Unit,
    private val failed: (Exception) -> Unit,
    private val muted: () -> Boolean,
) {
    private val stopped = AtomicBoolean(false)
    @Volatile private var recorder: AudioRecord? = null
    private var thread: Thread? = null

    fun start() {
        check(context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            "请允许麦克风权限后再开始收音。"
        }
        check(!cancelled.get())
        thread = Thread({ run() }, "yuepu-microphone").also { it.start() }
    }

    private fun run() {
        var vad: Vad? = null
        var echo: AcousticEchoCanceler? = null
        var noise: NoiseSuppressor? = null
        val stream = LiveSegmenter(emit)
        try {
            vad = Vad(config = VadModelConfig(sileroVadModelConfig = SileroVadModelConfig(
                model = File(modelRoot, "vad/silero_vad.onnx").absolutePath,
                threshold = sensitivity.threshold, minSpeechDuration = sensitivity.minSpeechSeconds,
                minSilenceDuration = .15f, maxSpeechDuration = 8f,
            ), sampleRate = 16000, numThreads = 1))
            val minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            check(minimum > 0) { "当前设备不支持 16 kHz 麦克风输入。" }
            if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
                throw SecurityException("麦克风权限已被撤销。")
            val input = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, 16000,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum, 16000))
            recorder = input
            check(input.state == AudioRecord.STATE_INITIALIZED) { "无法启用麦克风，请检查占用与权限。" }
            try {
                if (AcousticEchoCanceler.isAvailable()) echo = AcousticEchoCanceler.create(input.audioSessionId)?.also { it.enabled = true }
                if (sensitivity == Sensitivity.STANDARD && NoiseSuppressor.isAvailable())
                    noise = NoiseSuppressor.create(input.audioSessionId)?.also { it.enabled = true }
            } catch (_: UnsupportedOperationException) { }
            if (stopped.get() || cancelled.get()) return
            input.startRecording()
            check(input.recordingState == AudioRecord.RECORDSTATE_RECORDING) { "麦克风未能开始收音。" }
            if (!stopped.get() && !cancelled.get()) started()
            val pcm = ShortArray(512)
            var lastLevel = 0L
            while (!stopped.get() && !cancelled.get()) {
                val count = input.read(pcm, 0, pcm.size, AudioRecord.READ_BLOCKING)
                if (stopped.get() || cancelled.get()) break
                check(count > 0) { "麦克风输入已中断，请停止后重试。" }
                val samples = if (muted()) FloatArray(count) else FloatArray(count) { pcm[it] / 32768f }
                val detection = sensitivity.detectorInput(samples)
                vad.acceptWaveform(detection)
                while (!vad.empty()) vad.pop()
                stream.feed(samples, vad.isSpeechDetected())
                if (System.nanoTime() - lastLevel > 200_000_000L) {
                    val rms = sqrt(samples.sumOf { (it * it).toDouble() } / samples.size)
                    level((rms * 1600).toInt().coerceIn(0, 100))
                    lastLevel = System.nanoTime()
                }
            }
            if (!cancelled.get()) stream.flush()
        } catch (error: Exception) {
            if (!cancelled.get() && !stopped.get()) failed(error)
        } finally {
            try { recorder?.stop() } catch (_: IllegalStateException) { }
            recorder?.release(); recorder = null
            echo?.release(); noise?.release(); vad?.release()
            ended()
        }
    }

    fun stop() {
        stopped.set(true)
        try { recorder?.stop() } catch (_: IllegalStateException) { }
    }

    fun join() { thread?.join() }
}
