package org.yuepu.translate.core

import kotlin.math.abs

enum class Sensitivity(
    val key: String, val label: String, val threshold: Float,
    val minSpeechSeconds: Float, val maxGain: Float,
) {
    STANDARD("standard", "标准", .5f, .128f, 1f),
    SENSITIVE("sensitive", "灵敏", .35f, .096f, 8f);

    fun detectorInput(samples: FloatArray): FloatArray {
        val peak = samples.maxOfOrNull { abs(it) } ?: 0f
        val gain = minOf(maxGain, .1f / maxOf(peak, .0001f)).coerceAtLeast(1f)
        return if (gain > 1) FloatArray(samples.size) { samples[it] * gain } else samples
    }

    companion object {
        fun fromKey(key: String?) = entries.firstOrNull { it.key == key } ?: STANDARD
    }
}

enum class Direction(val source: String, val target: String, val label: String) {
    YUE_TO_ZH("yue", "zh", "粤语 → 普通话"),
    ZH_TO_YUE("zh", "yue", "普通话 → 粤语");
}
