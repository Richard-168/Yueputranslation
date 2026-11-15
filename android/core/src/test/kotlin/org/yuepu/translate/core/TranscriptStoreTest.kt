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
}
