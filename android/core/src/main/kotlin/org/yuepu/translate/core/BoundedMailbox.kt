package org.yuepu.translate.core

class BoundedMailbox<T : Any>(val maxFinals: Int = 3) {
    private val monitor = Object()
    private val finals = ArrayDeque<T>()
    private var draft: T? = null
    private var finished = false

    init { require(maxFinals > 0) }

    fun put(value: T, confirmed: Boolean): Boolean = synchronized(monitor) {
        if (finished) return false
        if (confirmed) {
            check(finals.size < maxFinals) { "处理跟不上收音，请暂停后重试。" }
            finals.addLast(value)
            draft = null
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
            if (finals.isNotEmpty()) return finals.removeFirst()
            if (draft != null) return draft.also { draft = null }
            if (finished) return null
            monitor.wait(50)
        }
        null
    }
}
