package org.yuepu.translate.core

import java.nio.ByteBuffer
import java.nio.ByteOrder

data class LocalSpeechVoice(
    val name: String, val language: String, val country: String,
    val networkRequired: Boolean, val installed: Boolean, val quality: Int,
)

object OfflineCantoneseVoice {
    fun select(voices: List<LocalSpeechVoice>): LocalSpeechVoice? = voices
        .filter { !it.networkRequired && it.installed &&
            (it.language.equals("yue", true) ||
                (it.language.equals("zh", true) && it.country.equals("HK", true))) }
        .sortedWith(compareByDescending<LocalSpeechVoice> { it.language.equals("yue", true) }
            .thenByDescending { it.quality }.thenBy { it.name })
        .firstOrNull()
}

data class PcmSpeech(val samples: FloatArray, val sampleRate: Int)

/** Bounded RIFF/WAVE decoding of a completed system TTS utterance. No audio devices. */
object PcmWave {
    fun decode(bytes: ByteArray): PcmSpeech {
        require(bytes.size in 44..16 * 1024 * 1024) { "系统译音文件大小无效。" }
        val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        fun tag(at: Int) = String(bytes, at, 4, Charsets.US_ASCII)
        require(tag(0) == "RIFF" && tag(8) == "WAVE") { "系统译音不是 WAV 音频。" }
        var offset = 12
        var format = 0; var channels = 0; var rate = 0; var bits = 0
        var audioAt = -1; var audioSize = 0
        while (offset + 8 <= bytes.size) {
            val size = buffer.getInt(offset + 4)
            val start = offset + 8
            require(size >= 0 && size <= bytes.size - start) { "系统译音文件不完整。" }
            when (tag(offset)) {
                "fmt " -> {
                    require(size >= 16)
                    format = buffer.getShort(start).toInt() and 65535
                    channels = buffer.getShort(start + 2).toInt() and 65535
                    rate = buffer.getInt(start + 4)
                    bits = buffer.getShort(start + 14).toInt() and 65535
                    if (format == 65534) {
                        require(size >= 40)
                        format = buffer.getShort(start + 24).toInt() and 65535
                    }
                }
                "data" -> { require(audioAt == -1); audioAt = start; audioSize = size }
            }
            offset = start + size + (size and 1)
        }
        require(channels in 1..2 && rate in 8000..48000 && audioAt >= 0 && audioSize > 0)
        require((format == 1 && bits in setOf(8, 16)) || (format == 3 && bits == 32)) {
            "手机离线语音使用了尚不支持的音频格式。"
        }
        val frameBytes = channels * bits / 8
        require(audioSize % frameBytes == 0 && audioSize / frameBytes <= rate * 30)
        buffer.position(audioAt)
        val samples = FloatArray(audioSize / frameBytes) {
            var total = 0f
            repeat(channels) {
                val value = when (bits) {
                    8 -> ((buffer.get().toInt() and 255) - 128) / 128f
                    16 -> buffer.short / 32768f
                    else -> buffer.float
                }
                require(value.isFinite()) { "系统译音包含无效采样。" }
                total += value.coerceIn(-1f, 1f)
            }
            total / channels
        }
        return PcmSpeech(samples, rate)
    }
}
