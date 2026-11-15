package org.yuepu.translate.engine

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import java.util.concurrent.CancellationException
import java.util.concurrent.atomic.AtomicBoolean

internal class SpeechPlayer : AutoCloseable {
    @Volatile private var track: AudioTrack? = null
    private var rate = 0
    private var frames = 0L

    fun write(samples: FloatArray, sampleRate: Int, cancelled: AtomicBoolean) {
        if (cancelled.get()) throw CancellationException()
        if (track == null || rate != sampleRate) {
            close()
            val minimum = AudioTrack.getMinBufferSize(sampleRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_FLOAT)
            check(minimum > 0) { "当前设备不支持此译音格式。" }
            track = AudioTrack.Builder()
                .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                .setAudioFormat(AudioFormat.Builder().setSampleRate(sampleRate)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_FLOAT).build())
                .setBufferSizeInBytes(maxOf(minimum, sampleRate / 5 * 4))
                .setTransferMode(AudioTrack.MODE_STREAM).build().also {
                    check(it.state == AudioTrack.STATE_INITIALIZED) { "无法启用译音输出。" }
                    it.play()
                }
            rate = sampleRate
            frames = 0
        }
        val output = checkNotNull(track)
        var offset = 0
        while (offset < samples.size) {
            if (cancelled.get()) throw CancellationException()
            val count = minOf(sampleRate / 20, samples.size - offset)
            val written = output.write(samples, offset, count, AudioTrack.WRITE_BLOCKING)
            if (cancelled.get()) throw CancellationException()
            check(written > 0) { "译音播放中断，请检查输出设备。" }
            offset += written
            frames += written
        }
    }

    fun drain(cancelled: AtomicBoolean) {
        val output = track ?: return
        val deadline = System.nanoTime() + 5_000_000_000L
        while ((output.playbackHeadPosition.toLong() and 0xffffffffL) < frames) {
            if (cancelled.get()) throw CancellationException()
            check(System.nanoTime() < deadline) { "译音输出没有响应，请检查设备。" }
            Thread.sleep(15)
        }
    }

    fun stop() {
        try { track?.stop(); track?.flush() } catch (_: IllegalStateException) { }
    }

    override fun close() {
        stop()
        track?.release()
        track = null
        rate = 0
    }
}
