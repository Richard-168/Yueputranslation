package org.yuepu.translate

import android.content.pm.PackageManager
import android.os.Bundle
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.yuepu.translate.core.Direction
import org.yuepu.translate.engine.*

/** Real ARM64 libraries and local weights. No microphone access, network, or speaker playback. */
@RunWith(AndroidJUnit4::class)
class OfflineRuntimeTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    @Test fun applicationDoesNotRequestNetworkOrBroadStoragePermissions() {
        @Suppress("DEPRECATION")
        val permissions = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)
            .requestedPermissions.orEmpty().toSet()
        assertEquals(setOf("android.permission.RECORD_AUDIO"), permissions)
    }

    @Test fun emptyInputAndMissingNativeModelReturnErrorsWithoutCrashing() {
        val error = CountDownLatch(1)
        val control = ConversationController(context, AppModels(context)) {
            if (it is SessionEvent.Error && it.text.contains("240")) error.countDown()
        }
        try {
            control.text(1, "", Direction.ZH_TO_YUE, false)
            assertTrue("Empty text must produce a visible validation error", error.await(10, TimeUnit.SECONDS))
        } finally { control.close() }
        try {
            NativeTranslator.create(context.filesDir.resolve("missing-model.gguf").absolutePath, 1)
            fail("Missing GGUF must be rejected")
        } catch (_: IllegalStateException) { }
    }

    @Test fun realModelsRecognizeTranslateAndSynthesizeBothDirections() {
        val models = AppModels(context)
        assertTrue("Import the prepared Android model pack before this test", models.importer.ready())
        models.importer.verify()
        val cancelled = AtomicBoolean(false)
        val engine = OfflineEngine(models.root)
        val started = SystemClock.elapsedRealtime()
        try {
            engine.load(Direction.ZH_TO_YUE, cancelled) { }
            metric("cold_load_ms", SystemClock.elapsedRealtime() - started)
            for ((direction, source) in listOf(
                Direction.ZH_TO_YUE to "你好，我想去香港西九龙高铁站。",
                Direction.YUE_TO_ZH to "唔该，我想去香港西九龙高铁站。",
            )) {
                val pcm = ArrayList<FloatArray>()
                var rate = 0
                var start = SystemClock.elapsedRealtime()
                engine.synthesize(source, direction.source, cancelled) { samples, sampleRate ->
                    assertTrue(samples.isNotEmpty() && samples.all { it.isFinite() })
                    pcm.add(samples.copyOf()); rate = sampleRate
                }
                metric("${direction.source}_tts_ms", SystemClock.elapsedRealtime() - start)
                assertTrue(rate in 8000..48000)
                val samples = pcm.fold(FloatArray(0)) { all, block -> all + block }
                assertTrue("Synthesis must emit audible PCM", samples.any { kotlin.math.abs(it) > .005f })
                engine.setDirection(direction)
                start = SystemClock.elapsedRealtime()
                val recognized = engine.recognize(resample(samples, rate), cancelled)
                metric("${direction.source}_asr_ms", SystemClock.elapsedRealtime() - start)
                assertTrue("Known synthesized station phrase must be recognized", recognized.contains("香港"))
                engine.resetTranslation()
                start = SystemClock.elapsedRealtime()
                val translated = engine.translate(source, direction, cancelled)
                metric("${direction.source}_mt_ms", SystemClock.elapsedRealtime() - start)
                assertTrue("Translation must preserve the station destination", translated.contains("香港"))
                var output = 0
                engine.synthesize(translated, direction.target, cancelled) { block, _ -> output += block.size }
                assertTrue("Translated speech must contain audio", output > 1600)
                engine.resetTranslation()
                val semanticSource = if (direction.source == "yue") "佢今日唔得闲，唔该听日再嚟。" else "他今天没空，请明天再来。"
                val semanticTarget = engine.translate(semanticSource, direction, cancelled)
                if (direction.target == "yue") {
                    assertTrue("Mandarin must be converted to Cantonese vocabulary", semanticTarget.contains("佢"))
                    assertTrue("Tomorrow must remain tomorrow", semanticTarget.contains("聽日") || semanticTarget.contains("听日"))
                } else {
                    assertTrue("Cantonese must be converted to Mandarin vocabulary", semanticTarget.contains("他") || semanticTarget.contains("她"))
                    assertTrue("Tomorrow must remain tomorrow", semanticTarget.contains("明天"))
                }
            }
            engine.cancel()
            try { engine.translate("你好", Direction.ZH_TO_YUE, cancelled); fail("Cancelled JNI request must fail") }
            catch (_: IllegalStateException) { }
            engine.resetTranslation()
            assertTrue(engine.translate("你好", Direction.YUE_TO_ZH, cancelled).isNotBlank())
        } finally { engine.close() }
    }

    private fun resample(input: FloatArray, rate: Int): FloatArray {
        val count = (input.size.toLong() * 16000 / rate).toInt()
        require(count <= 128000) { "Synthetic test phrase exceeded the capture window" }
        return FloatArray(count) { index ->
            val at = index.toDouble() * rate / 16000
            val left = at.toInt().coerceAtMost(input.lastIndex)
            val right = (left + 1).coerceAtMost(input.lastIndex)
            (input[left] * (1 - (at - left)) + input[right] * (at - left)).toFloat()
        }
    }
    private fun metric(name: String, value: Long) {
        instrumentation.sendStatus(2, Bundle().apply { putString("stream", "MODEL_METRIC $name=$value\n") })
    }
}
