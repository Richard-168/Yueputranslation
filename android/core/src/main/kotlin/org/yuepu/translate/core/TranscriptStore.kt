package org.yuepu.translate.core

class TranscriptStore(val maxRows: Int = 200, val maxCharacters: Int = 200_000) {
    private val entries = linkedMapOf<Pair<Long, Long>, Caption>()
    private var epoch = 0L
    private var active = false
    private var removedThrough = -1L
    private var characters = 0
    private var language = "yue"

    init { require(maxRows > 0 && maxCharacters > 0) }

    fun begin(sourceLanguage: String = "yue"): Long {
        require(sourceLanguage in listOf("yue", "zh"))
        language = sourceLanguage
        active = true
        removedThrough = -1
        return ++epoch
    }

    fun source(epoch: Long, block: Long, version: Long, text: String, final: Boolean): Boolean {
        if (!active || epoch != this.epoch || block <= removedThrough || text.isBlank() ||
            text.length > maxCharacters) return false
        val key = epoch to block
        val previous = entries[key]
        if (previous != null && (previous.final || version <= previous.version)) return false
        val updated = Caption(block, text, previous?.target.orEmpty(), final,
            epoch, version, previous?.createdAt ?: System.currentTimeMillis(),
            previous?.targetVersion ?: -1, language)
        characters += updated.source.length + updated.target.length -
            (previous?.let { it.source.length + it.target.length } ?: 0)
        entries[key] = updated
        prune()
        return true
    }

    fun translation(epoch: Long, block: Long, version: Long, text: String, preview: Boolean = false): Boolean {
        if (!active || epoch != this.epoch) return false
        val key = epoch to block
        val previous = entries[key] ?: return false
        if (previous.targetFinal || text.isBlank() ||
            previous.source.length + text.length > maxCharacters) return false
        if (preview) {
            if (previous.final || version > previous.version || version <= previous.targetVersion) return false
        } else if (previous.version != version) return false
        characters += text.length - previous.target.length
        entries[key] = previous.copy(target = text, targetVersion = version)
        prune()
        return true
    }

    fun cancel() { active = false }
    fun snapshot(): List<Caption> = entries.values.toList()
    fun clear() { entries.clear(); characters = 0 }

    private fun prune() {
        while (entries.size > maxRows || characters > maxCharacters) {
            val iterator = entries.entries.iterator()
            val removed = iterator.next().value
            characters -= removed.source.length + removed.target.length
            if (removed.epoch == epoch) removedThrough = maxOf(removedThrough, removed.block)
            iterator.remove()
        }
    }
}

data class Caption(
    val block: Long, val source: String, val target: String, val final: Boolean,
    val epoch: Long = 0, val version: Long = 0, val createdAt: Long = 0,
    val targetVersion: Long = -1, val sourceLanguage: String = "yue",
) {
    val targetFinal: Boolean get() = final && targetVersion == version
}
