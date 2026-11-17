package org.yuepu.translate.core

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
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

    @Test fun captureStopsAtTheLimitAndDrainsAcceptedFinals() {
        val queue = BoundedMailbox<String>(maxFinals = 2, stopAtLimit = true)
        assertTrue(queue.put("first", true))
        assertTrue(queue.put("draft", false))
        assertThrows(MailboxBacklog::class.java) { queue.put("last", true) }
        assertFalse(queue.put("too late", true))
        assertEquals("first", queue.take { false })
        assertEquals("last", queue.take { false })
        assertNull(queue.take { false })
    }

    @Test fun recognitionCanWaitForTheTranslationQueueAndCancelPromptly() {
        val queue = BoundedMailbox<String>(maxFinals = 1)
        val worker = Executors.newSingleThreadExecutor()
        try {
            assertTrue(queue.put("first", true))
            val entering = CountDownLatch(1)
            val waiting = worker.submit<Boolean> {
                queue.put("next", true) {
                    entering.countDown()
                    false
                }
            }
            assertTrue(entering.await(2, TimeUnit.SECONDS))
            assertFalse(waiting.isDone)
            assertEquals("first", queue.take { false })
            assertTrue(waiting.get(2, TimeUnit.SECONDS))
            assertEquals("next", queue.take { false })
            assertTrue(queue.put("another", true))
            val enteringAgain = CountDownLatch(1)
            val cancelled = worker.submit<Boolean> {
                queue.put("cancelled", true) {
                    enteringAgain.countDown()
                    false
                }
            }
            assertTrue(enteringAgain.await(2, TimeUnit.SECONDS))
            assertFalse(cancelled.isDone)
            queue.cancel()
            assertFalse(cancelled.get(2, TimeUnit.SECONDS))
            assertNull(queue.take { false })
        } finally {
            queue.cancel()
            worker.shutdownNow()
        }
    }
}
