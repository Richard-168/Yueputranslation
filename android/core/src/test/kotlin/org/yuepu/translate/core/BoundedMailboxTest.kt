package org.yuepu.translate.core

import org.junit.Assert.*
import org.junit.Test

class BoundedMailboxTest {
    @Test fun draftsCoalesceAndConfirmedWorkHasPriority() {
        val queue = BoundedMailbox<String>()
        for (index in 0..1000) assertTrue(queue.put("draft-$index", false))
        assertTrue(queue.put("final-0", true))
        assertTrue(queue.put("draft-next", false))
        queue.finish()
        assertEquals("final-0", queue.take { false })
        assertEquals("draft-next", queue.take { false })
        assertNull(queue.take { false })
        assertFalse(queue.put("late", true))
    }

    @Test fun overloadIsExplicitAndCancellationDiscardsPendingAudio() {
        val queue = BoundedMailbox<String>(maxFinals = 1)
        assertTrue(queue.put("first", true))
        assertThrows(IllegalStateException::class.java) { queue.put("overload", true) }
        queue.cancel()
        assertNull(queue.take { false })
        assertFalse(queue.put("late", false))
    }
}
