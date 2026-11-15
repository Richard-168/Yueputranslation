package org.yuepu.translate.core

import java.io.File
import java.io.InputStream
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.CancellationException
import java.util.zip.ZipInputStream

data class ModelFile(val path: String, val size: Long, val sha256: String)

class ModelPackImporter(val directory: File, val expected: List<ModelFile>) {
    init {
        require(expected.isNotEmpty() && expected.size <= 64)
        require(expected.map { it.path }.toSet().size == expected.size)
        require(expected.all {
            it.size in 1..(2L * 1024 * 1024 * 1024) &&
                it.sha256.matches(Regex("[0-9a-f]{64}")) &&
                it.path.matches(Regex("[a-zA-Z0-9_./-]+")) &&
                !it.path.startsWith("/") && it.path.split('/').none { part -> part in listOf("", ".", "..") }
        })
        require(expected.sumOf { it.size } <= 3L * 1024 * 1024 * 1024)
    }

    fun install(input: InputStream, cancelled: () -> Boolean = { false }, progress: (Long) -> Unit = {}): File {
        fun checkCancelled() { if (cancelled()) throw CancellationException("已取消模型导入") }
        checkCancelled()
        directory.mkdirs()
        require(directory.isDirectory) { "模型目录不可写。" }
        recoverPrevious()
        directory.listFiles()?.filter { it.isDirectory && it.name.startsWith(".incoming-") }
            ?.forEach(::removePrivateStage)
        require(directory.usableSpace > expected.sumOf { it.size } + 64L * 1024 * 1024) { "手机可用空间不足。" }
        val incoming = File(directory, ".incoming-${UUID.randomUUID()}")
        val backup = File(directory, ".backup-${UUID.randomUUID()}")
        val active = File(directory, "active")
        val known = expected.associateBy { it.path }
        val received = mutableSetOf<String>()
        var total = 0L
        incoming.mkdirs()
        try {
            ZipInputStream(input.buffered()).use { zip ->
                while (true) {
                    checkCancelled()
                    val entry = zip.nextEntry ?: break
                    require(!entry.isDirectory) { "模型包包含非预期目录条目。" }
                    if (entry.name == "manifest.json") {
                        require(!received.contains(entry.name)) { "模型包存在重复文件。" }
                        received.add(entry.name)
                        var size = 0
                        val buffer = ByteArray(4096)
                        while (true) {
                            checkCancelled()
                            val count = zip.read(buffer)
                            if (count < 0) break
                            size += count
                            require(size <= 65536) { "模型清单过大。" }
                        }
                        continue
                    }
                    val spec = known[entry.name] ?: throw IllegalArgumentException("模型包包含非预期文件。")
                    require(received.add(entry.name)) { "模型包存在重复文件。" }
                    require(entry.size == -1L || entry.size == spec.size) { "模型大小不匹配。" }
                    val target = File(incoming, entry.name)
                    require(target.canonicalPath.startsWith(incoming.canonicalPath + File.separator)) { "模型路径越界。" }
                    target.parentFile!!.mkdirs()
                    val digest = MessageDigest.getInstance("SHA-256")
                    var size = 0L
                    target.outputStream().buffered().use { output ->
                        val buffer = ByteArray(65536)
                        while (true) {
                            checkCancelled()
                            val count = zip.read(buffer)
                            if (count < 0) break
                            size += count
                            require(size <= spec.size) { "模型文件超出预期大小。" }
                            digest.update(buffer, 0, count)
                            output.write(buffer, 0, count)
                            total += count
                            progress(total)
                        }
                    }
                    require(size == spec.size && hex(digest.digest()) == spec.sha256) { "模型校验失败。" }
                }
            }
            require(received.containsAll(known.keys)) { "模型包不完整。" }
            checkCancelled()
            if (active.exists()) check(active.renameTo(backup)) { "无法保留当前模型，请停止处理后重试。" }
            if (!incoming.renameTo(active)) {
                if (backup.exists()) check(backup.renameTo(active)) { "无法恢复原模型。" }
                error("无法安装新模型。")
            }
            if (backup.exists()) removePrivateStage(backup)
            return active
        } finally {
            // Only this invocation's private staging directory is removed.
            if (incoming.exists()) removePrivateStage(incoming)
        }
    }

    fun ready(): Boolean {
        recoverPrevious()
        return expected.all { spec ->
        val file = File(directory, "active/${spec.path}")
        file.isFile && file.length() == spec.size
        }
    }

    private fun recoverPrevious() {
        val active = File(directory, "active")
        if (active.exists()) return
        val backup = directory.listFiles()?.filter { it.isDirectory && it.name.startsWith(".backup-") }
            ?.maxByOrNull { it.lastModified() } ?: return
        check(backup.canonicalFile.parentFile == directory.canonicalFile)
        check(backup.renameTo(active)) { "无法恢复原模型，请稍后重试。" }
    }

    fun verify(cancelled: () -> Boolean = { false }) {
        require(ready()) { "请先导入完整的 Android 模型包。" }
        for (spec in expected) {
            val digest = MessageDigest.getInstance("SHA-256")
            File(directory, "active/${spec.path}").inputStream().buffered().use { input ->
                val buffer = ByteArray(1024 * 1024)
                while (true) {
                    if (cancelled()) throw CancellationException("已取消模型检查")
                    val count = input.read(buffer)
                    if (count < 0) break
                    digest.update(buffer, 0, count)
                }
            }
            require(hex(digest.digest()) == spec.sha256) { "模型已损坏，请重新导入。" }
        }
    }

    private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it) }

    private fun removePrivateStage(stage: File) {
        check(stage.parentFile.canonicalFile == directory.canonicalFile &&
            (stage.name.startsWith(".incoming-") || stage.name.startsWith(".backup-")))
        // Windows file scanners may briefly retain freshly closed staging files;
        // cleanup is bounded and never touches a user-selected source directory.
        repeat(3) { attempt ->
            if (!stage.exists() || stage.deleteRecursively()) return
            Thread.sleep(20L * (attempt + 1))
        }
        check(!stage.exists()) { "无法清理模型导入缓存，请稍后重试。" }
    }
}
