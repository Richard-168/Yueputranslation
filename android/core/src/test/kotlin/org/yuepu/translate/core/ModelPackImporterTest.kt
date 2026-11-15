package org.yuepu.translate.core

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.util.concurrent.CancellationException
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import org.junit.Assert.*
import org.junit.Test

class ModelPackImporterTest {
    private val bytes = "synthetic model boundary fixture".toByteArray()
    private val digest = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    private val expected = listOf(ModelFile("asr/model.bin", bytes.size.toLong(), digest))

    private fun archive(vararg entries: Pair<String, ByteArray>): ByteArrayInputStream {
        val output = ByteArrayOutputStream()
        ZipOutputStream(output).use { zip ->
            for ((path, content) in entries) {
                zip.putNextEntry(ZipEntry(path))
                zip.write(content)
                zip.closeEntry()
            }
        }
        return ByteArrayInputStream(output.toByteArray())
    }

    private fun root(block: (File) -> Unit) {
        val root = Files.createTempDirectory("yuepu-model-test-").toFile()
        try { block(root) } finally { root.deleteRecursively() }
    }

    @Test fun validPackIsInstalledOnlyAfterValidation() = root { root ->
        val active = ModelPackImporter(root, expected).install(archive("asr/model.bin" to bytes))
        assertTrue(File(active, "asr/model.bin").isFile)
        assertArrayEquals(bytes, File(active, "asr/model.bin").readBytes())
    }

    @Test fun interruptedSwitchRestoresOldModelsAndRetryRemovesOnlyPrivateStages() = root { root ->
        val old = File(root, ".backup-interrupted").apply { mkdirs() }
        File(old, "asr").mkdirs()
        File(old, "asr/model.bin").writeBytes(bytes)
        File(root, ".incoming-interrupted").apply { mkdirs(); resolve("partial").writeText("partial") }
        val importer = ModelPackImporter(root, expected)
        assertTrue("A process restart must recover the previous installation", importer.ready())
        importer.verify()
        importer.install(archive("asr/model.bin" to bytes))
        assertEquals(listOf("active"), root.list()!!.toList())
    }

    @Test fun zipSlipUnknownFileAndOversizedEntryAreRejected() = root { root ->
        val importer = ModelPackImporter(root, expected)
        for (entry in listOf("../escape.bin" to bytes, "unknown.bin" to bytes,
            "asr/model.bin" to (bytes + byteArrayOf(1)))) {
            assertThrows(IllegalArgumentException::class.java) { importer.install(archive(entry)) }
        }
        assertFalse(File(root.parentFile, "escape.bin").exists())
        assertFalse(File(root, "active").exists())
    }

    @Test fun wrongDigestMissingFileAndCancellationKeepExistingInstallation() = root { root ->
        val active = File(root, "active").apply { mkdirs() }
        File(active, "keep.txt").writeText("previous verified models")
        val importer = ModelPackImporter(root, expected)
        assertThrows(IllegalArgumentException::class.java) {
            importer.install(archive("asr/model.bin" to ByteArray(bytes.size)))
        }
        assertThrows(IllegalArgumentException::class.java) { importer.install(archive()) }
        assertThrows(CancellationException::class.java) {
            importer.install(archive("asr/model.bin" to bytes), cancelled = { true })
        }
        assertEquals("previous verified models", File(active, "keep.txt").readText())
        assertEquals(listOf("active"), root.list()!!.toList())
    }
}
