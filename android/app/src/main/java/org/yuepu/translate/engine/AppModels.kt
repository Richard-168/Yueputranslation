package org.yuepu.translate.engine

import android.content.Context
import java.io.File
import org.json.JSONObject
import org.yuepu.translate.core.ModelFile
import org.yuepu.translate.core.ModelPackImporter

internal class AppModels(context: Context) {
    val files: List<ModelFile>
    val directory = File(context.filesDir, "models")
    val importer: ModelPackImporter
    val root: File get() = File(directory, "active")
    val bytes: Long get() = files.sumOf { it.size }

    init {
        val catalog = context.assets.open("model-catalog.json").bufferedReader().use { JSONObject(it.readText()) }
        require(catalog.getInt("format") == 1)
        val values = catalog.getJSONArray("files")
        files = (0 until values.length()).map { index ->
            val item = values.getJSONObject(index)
            ModelFile(item.getString("path"), item.getLong("size"), item.getString("sha256"))
        }
        importer = ModelPackImporter(directory, files)
    }
}
