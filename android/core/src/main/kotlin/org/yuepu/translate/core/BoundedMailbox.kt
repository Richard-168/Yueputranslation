package org.yuepu.translate.core

class MailboxBacklog : IllegalStateException("处理跟不上收音，请暂停后重试。")

class BoundedMailbox<T : Any>(val maxFinals: Int = 3, private val stopAtLimit: Boolean = false) {
    private val monitor = Object()
    private val finals = ArrayDeque<T>()
    private var draft: T? = null
    private var finished = false

    init { require(maxFinals > 0) }

    fun put(value: T, confirmed: Boolean, cancelled: (() -> Boolean)? = null): Boolean = synchronized(monitor) {
        if (finished || cancelled?.invoke() == true) return false
        if (confirmed) {
            while (finals.size >= maxFinals) {
                if (cancelled == null) throw MailboxBacklog()
                monitor.wait(50)
                if (finished || cancelled()) return false
            }
            finals.addLast(value)
            draft = null
            if (stopAtLimit && finals.size == maxFinals) {
                // Accept the last window before stopping capture. The consumer still drains the queue.
                finished = true
                monitor.notifyAll()
                throw MailboxBacklog()
            }
        } else draft = value
        monitor.notifyAll()
        true
    }

    fun finish() = synchronized(monitor) { finished = true; monitor.notifyAll() }
    fun cancel() = synchronized(monitor) {
        finished = true
        finals.clear()
        draft = null
        monitor.notifyAll()
    }

    fun take(cancelled: () -> Boolean): T? = synchronized(monitor) {
        while (!cancelled()) {
            if (finals.isNotEmpty()) return finals.removeFirst().also { monitor.notifyAll() }
            if (draft != null) return draft.also { draft = null }
            if (finished) return null
            monitor.wait(50)
        }
        null
    }
}
