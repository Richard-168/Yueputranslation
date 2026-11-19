package org.yuepu.translate.core

import org.junit.Assert.*
import org.junit.Test

class TranscriptStoreTest {
    @Test fun coarseTranslationMayLagActiveSourceButCannotReplaceConfirmedText() {
        val store = TranscriptStore()
        val epoch = store.begin()
        store.source(epoch, 0, 1, "今天", false)
        store.source(epoch, 0, 2, "今天下午", false)
        assertTrue(store.translation(epoch, 0, 1, "今日", preview = true))
        store.source(epoch, 0, 3, "今天下午三点。", true)
        assertFalse(store.translation(epoch, 0, 2, "今日下晝", preview = true))
        assertTrue(store.translation(epoch, 0, 3, "今日下晝三點。"))
        assertEquals("今日下晝三點。", store.snapshot().single().target)
    }
    @Test fun lateDraftCannotReplaceConfirmedSourceOrTranslation() {
        val store = TranscriptStore()
        val epoch = store.begin()
        assertTrue(store.source(epoch, 0, 1, "香港西九龙", false))
        assertTrue(store.source(epoch, 0, 2, "香港西九龙高铁站。", true))
        assertFalse(store.translation(epoch, 0, 1, "旧译文"))
        assertTrue(store.translation(epoch, 0, 2, "香港西九龍高鐵站。"))
        assertFalse(store.source(epoch, 0, 3, "迟到的草稿", false))
        assertEquals("香港西九龙高铁站。", store.snapshot().single().source)
        assertEquals("香港西九龍高鐵站。", store.snapshot().single().target)
    }

    @Test fun cancelAndNextSessionRejectEveryOldEventButKeepExistingRows() {
        val store = TranscriptStore()
        val before = store.begin()
        assertTrue(store.source(before, 0, 1, "保留字幕", true))
        store.cancel()
        assertFalse(store.translation(before, 0, 1, "取消后的结果"))
        val after = store.begin()
        assertTrue(after > before)
        assertFalse(store.source(before, 1, 1, "旧会话", true))
        assertTrue(store.source(after, 0, 1, "新会话", true))
        assertEquals(listOf("保留字幕", "新会话"), store.snapshot().map { it.source })
    }

    @Test fun evictionBoundsMemoryAndOldEventsCannotRecreateRemovedRows() {
        val store = TranscriptStore(maxRows = 2, maxCharacters = 12)
        val epoch = store.begin()
        for (block in 0L..4L) assertTrue(store.source(epoch, block, 1, "短句", true))
        assertEquals(listOf(3L, 4L), store.snapshot().map { it.block })
        assertFalse(store.source(epoch, 0, 2, "旧记录", true))
        assertTrue(store.translation(epoch, 4, 1, "译文"))
        assertTrue(store.snapshot().sumOf { it.source.length + it.target.length } <= 12)
    }

    @Test fun restoredHistoryRejectsQueuedEventsAndNewWorkUsesUnusedEpochs() {
        val store = TranscriptStore()
        val previous = store.begin()
        store.source(previous, 0, 1, "本次草稿", false)
        val restored = Caption(
            block = 0, source = "早晨。", target = "早上好。", final = true,
            epoch = 8, version = 3, createdAt = 100, targetVersion = 3,
        )
        store.restore(listOf(restored))
        assertFalse(store.source(previous, 1, 1, "迟到的草稿", false))
        assertFalse(store.translation(restored.epoch, 0, 3, "不应写入"))
        assertEquals(listOf(restored), store.snapshot())
        assertTrue(store.snapshot().single().targetFinal)

        val next = store.begin("zh")
        assertTrue(next > restored.epoch)
        assertTrue(store.source(next, 0, 1, "继续翻译", true))
        assertEquals(listOf("yue", "zh"), store.snapshot().map { it.sourceLanguage })
        store.restore(emptyList())
        assertFalse(store.source(next, 0, 2, "迟到的确认", true))
        assertTrue(store.begin() > next)
    }

    @Test fun restoringHistoryHonorsRowAndCharacterLimits() {
        val store = TranscriptStore(maxRows = 2, maxCharacters = 5)
        val saved = listOf(
            Caption(0, "甲", "甲译", true),
            Caption(1, "乙", "乙译", true),
            Caption(2, "丙", "丙", true),
            Caption(3, "丁", "丁", true),
        )
        store.restore(saved)
        assertEquals(saved.takeLast(2), store.snapshot())
        store.restore(saved.take(2))
        assertEquals(saved.take(2).takeLast(1), store.snapshot())
    }
}
