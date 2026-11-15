package org.yuepu.translate.core

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.*
import org.junit.Test

class OfflineSpeechTest {
    @Test fun voiceSelectionRejectsNetworkUninstalledAndMandarinVoices() {
        val voices = listOf(
            LocalSpeechVoice("network", "yue", "HK", true, true, 500),
            LocalSpeechVoice("missing", "yue", "HK", false, false, 500),
            LocalSpeechVoice("mandarin", "zh", "CN", false, true, 500),
            LocalSpeechVoice("hong-kong", "zh", "HK", false, true, 200),
            LocalSpeechVoice("cantonese", "yue", "HK", false, true, 300),
        )
        assertEquals("cantonese", OfflineCantoneseVoice.select(voices)?.name)
        assertEquals("hong-kong", OfflineCantoneseVoice.select(voices.take(4))?.name)
        assertNull(OfflineCantoneseVoice.select(voices.take(3)))
    }

    private fun wav(samples: ShortArray, channels: Int = 1): ByteArray {
        val body = samples.size * 2
        return ByteBuffer.allocate(44 + body).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray()); putInt(36 + body); put("WAVEfmt ".toByteArray())
            putInt(16); putShort(1); putShort(channels.toShort()); putInt(16000)
            putInt(16000 * channels * 2); putShort((channels * 2).toShort()); putShort(16)
            put("data".toByteArray()); putInt(body)
            samples.forEach { putShort(it) }
        }.array()
    }

    @Test fun systemWaveIsDecodedToFiniteMonoPcmWithoutOpeningSpeakers() {
        val decoded = PcmWave.decode(wav(shortArrayOf(16384, 0, -16384, -16384), 2))
        assertEquals(16000, decoded.sampleRate)
        assertArrayEquals(floatArrayOf(.25f, -.5f), decoded.samples, .00001f)
    }

    @Test fun malformedAndTruncatedSystemAudioIsRejected() {
        for (data in listOf(ByteArray(0), wav(shortArrayOf(1)).copyOf(44), wav(shortArrayOf()))) {
            try { PcmWave.decode(data); fail("Invalid system audio was accepted") }
            catch (_: IllegalArgumentException) { }
        }
    }
}
