package org.yuepu.translate.core

data class AudioWindow(
    val block: Long, val version: Long, val samples: FloatArray, val final: Boolean,
    val start: Long, val end: Long, val voiceEnd: Long,
)

class LiveSegmenter(private val emit: (AudioWindow) -> Unit) {
    private val capacity = 8 * 16000 + 5120 + 512
    private val ring = FloatArray(capacity)
    private var end = 0L
    private var origin: Long? = null
    private var voiceEnd = 0L
    private var nextUpdate = 0L
    private var lastFinalEnd = 0L
    private var block = 0L

    fun feed(samples: FloatArray, voiced: Boolean) {
        require(samples.isNotEmpty() && samples.size <= 512 && samples.all { it.isFinite() })
        for (value in samples) { ring[(end % capacity).toInt()] = value; end++ }
        if (voiced) {
            voiceEnd = end
            if (origin == null) {
                origin = maxOf(lastFinalEnd, end - maxOf(5120, samples.size))
                nextUpdate = origin!! + 12800
            }
        }
        val start = origin ?: return
        if (end - start >= 128000) {
            val cut = start + 128000
            window(cut, true)
            if (voiceEnd > cut) {
                origin = cut
                nextUpdate = cut + 12800
            }
        } else if (!voiced && end - voiceEnd >= 10400) {
            window(end, true)
        } else if (end >= nextUpdate) window(end, false)
    }

    fun flush() { if (origin != null) window(end, true) }

    private fun window(right: Long, final: Boolean) {
        val start = origin ?: return
        require(start >= maxOf(0, end - capacity) && right > start && right <= end)
        val audio = FloatArray((right - start).toInt()) { ring[((start + it) % capacity).toInt()] }
        emit(AudioWindow(block, right * 2 + if (final) 1 else 0, audio, final,
            start, right, minOf(voiceEnd, right)))
        nextUpdate = right + 10240
        if (final) { block++; origin = null; lastFinalEnd = right }
    }
}
