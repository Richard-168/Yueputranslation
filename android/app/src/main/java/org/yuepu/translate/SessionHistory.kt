package org.yuepu.translate

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject
import org.yuepu.translate.core.Caption
import org.yuepu.translate.core.TranscriptStore

internal data class SavedSession(val id: String, val title: String, val updatedAt: Long)

/** Stores transcript text and its display metadata in an app-private database. */
internal class SessionHistory(context: Context) : AutoCloseable {
    private val helper = object : SQLiteOpenHelper(context.applicationContext, "sessions.db", null, 1) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL(
                """CREATE TABLE sessions (
                    id TEXT PRIMARY KEY NOT NULL,
                    title TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    captions TEXT NOT NULL
                )""",
            )
            db.execSQL("CREATE INDEX sessions_recency ON sessions(updated_at DESC, id ASC)")
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            error("不支持的会话历史格式。")
        }
    }

    fun list(): List<SavedSession> = helper.readableDatabase.query(
        "sessions", arrayOf("id", "title", "updated_at"),
        null, null, null, null, "updated_at DESC, id ASC",
    ).use { cursor ->
        buildList {
            while (cursor.moveToNext()) {
                add(SavedSession(cursor.getString(0), cursor.getString(1), cursor.getLong(2)))
            }
        }
    }

    fun load(id: String): List<Caption> {
        val json = helper.readableDatabase.query(
            "sessions", arrayOf("captions"), "id = ?", arrayOf(id), null, null, null,
        ).use { if (it.moveToFirst()) it.getString(0) else return emptyList() }
        val rows = JSONArray(json)
        require(rows.length() <= TranscriptStore.DEFAULT_MAX_ROWS) { "会话条数超出上限。" }
        return List(rows.length()) { index ->
            val row = rows.getJSONObject(index)
            Caption(
                block = row.getLong("block"),
                source = row.getString("source"),
                target = row.getString("target"),
                final = row.getBoolean("final"),
                epoch = row.getLong("epoch"),
                version = row.getLong("version"),
                createdAt = row.getLong("createdAt"),
                targetVersion = row.getLong("targetVersion"),
                sourceLanguage = row.getString("sourceLanguage"),
            )
        }.also(::validate)
    }

    fun save(id: String, captions: List<Caption>) {
        if (captions.isEmpty()) return
        validate(captions)
        val payload = JSONArray()
        for (caption in captions) {
            payload.put(JSONObject().apply {
                put("block", caption.block)
                put("source", caption.source)
                put("target", caption.target)
                put("final", caption.final)
                put("epoch", caption.epoch)
                put("version", caption.version)
                put("createdAt", caption.createdAt)
                put("targetVersion", caption.targetVersion)
                put("sourceLanguage", caption.sourceLanguage)
            })
        }
        val serialized = payload.toString()
        val database = helper.writableDatabase
        database.beginTransaction()
        try {
            val previous = database.query(
                "sessions", arrayOf("captions"), "id = ?", arrayOf(id), null, null, null,
            ).use { if (it.moveToFirst()) it.getString(0) else null }
            if (serialized != previous) {
                database.execSQL(
                    "INSERT OR REPLACE INTO sessions (id, title, updated_at, captions) VALUES (?, ?, ?, ?)",
                    arrayOf(id, title(captions.first().source), System.currentTimeMillis(), serialized),
                )
            }
            database.setTransactionSuccessful()
        } finally {
            database.endTransaction()
        }
    }

    fun delete(id: String) {
        helper.writableDatabase.delete("sessions", "id = ?", arrayOf(id))
    }

    override fun close() = helper.close()

    private fun validate(captions: List<Caption>) {
        require(captions.size <= TranscriptStore.DEFAULT_MAX_ROWS) { "会话条数超出上限。" }
        require(captions.sumOf { it.source.length.toLong() + it.target.length } <=
            TranscriptStore.DEFAULT_MAX_CHARACTERS) { "会话字数超出上限。" }
        require(captions.all { it.sourceLanguage == "yue" || it.sourceLanguage == "zh" }) {
            "会话包含无法识别的语言。"
        }
    }

    private fun title(source: String): String {
        val heading = source.trim().replace(Regex("\\s+"), " ")
        if (heading.codePointCount(0, heading.length) <= 36) return heading.ifEmpty { "会话" }
        return heading.substring(0, heading.offsetByCodePoints(0, 36)) + "…"
    }
}
