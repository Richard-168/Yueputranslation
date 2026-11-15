package org.yuepu.translate.core

import org.junit.Assert.*
import org.junit.Test

class LiveSegmenterTest {
    @Test fun shortReplyAfterIdleRetainsItsBeginningAndFinalizesWithoutMoreSpeech() {
        val windows = mutableListOf<AudioWindow>()
        val stream = LiveSegmenter(windows::add)
        repeat(150) { stream.feed(FloatArray(512), false) }
        repeat(6) { stream.feed(FloatArray(512) { .006f }, true) }
        repeat(24) { stream.feed(FloatArray(512), false) }
        assertTrue(windows.any { it.final })
        assertEquals(6 * 512, windows.single { it.final }.samples.count { it == .006f })
        val count = windows.size
        stream.flush()
        assertEquals(count, windows.size)
    }

    @Test fun continuousAudioIsBoundedAndFinalWindowsPreserveEverySample() {
        val windows = mutableListOf<AudioWindow>()
        val stream = LiveSegmenter(windows::add)
        val original = FloatArray(20 * 16000) { it.toFloat() / 1000000 }
        for (start in original.indices step 512) {
            stream.feed(original.copyOfRange(start, minOf(start + 512, original.size)), true)
        }
        stream.flush()
        val finals = windows.filter { it.final }
        assertEquals(3, finals.size)
        assertTrue(windows.all { it.samples.size <= 8 * 16000 })
        assertArrayEquals(original, finals.flatMap { it.samples.asList() }.toFloatArray(), 0f)
        assertEquals(listOf(0L, 1L, 2L), finals.map { it.block })
    }

    @Test fun silenceDoesNotOpenAWindowAndInvalidPcmIsRejected() {
        val windows = mutableListOf<AudioWindow>()
        val stream = LiveSegmenter(windows::add)
        repeat(1000) { stream.feed(FloatArray(512), false) }
        stream.flush()
        assertTrue(windows.isEmpty())
        assertThrows(IllegalArgumentException::class.java) {
            stream.feed(floatArrayOf(Float.NaN), true)
        }
    }

    @Test fun forcedBoundaryPreservesTheTailOfTheLastVoicedFrame() {
        val windows = mutableListOf<AudioWindow>()
        val stream = LiveSegmenter(windows::add)
        // An utterance begins after a non-aligned frame, so the 8 s boundary
        // falls inside a later frame. Its remainder must survive immediate stop.
        stream.feed(FloatArray(173), false)
        repeat(250) { stream.feed(FloatArray(512) { .01f }, true) }
        stream.flush()
        assertTrue(windows.all { it.samples.size <= 128000 })
        assertEquals(250 * 512, windows.filter { it.final }.sumOf { it.samples.count { value -> value == .01f } })
    }

    @Test fun pauseNearMaximumDurationNeverProducesAnOversizedRecognitionWindow() {
        val windows = mutableListOf<AudioWindow>()
        val stream = LiveSegmenter(windows::add)
        stream.feed(FloatArray(173), false)
        repeat(229) { stream.feed(FloatArray(512) { .01f }, true) }
        repeat(30) { stream.feed(FloatArray(512), false) }
        stream.flush()
        assertTrue(windows.all { it.samples.size <= 128000 })
    }
}
