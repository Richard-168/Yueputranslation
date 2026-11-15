package org.yuepu.translate

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.text.InputFilter
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.*
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import org.yuepu.translate.core.*
import org.yuepu.translate.engine.*

/** Foreground-only capture. Conversation content remains in memory until explicit export. */
class MainActivity : Activity() {
    private val background = Color.rgb(18, 22, 23)
    private val surface = Color.rgb(32, 38, 39)
    private val ink = Color.rgb(241, 244, 240)
    private val muted = Color.rgb(176, 188, 184)
    private val yellow = Color.rgb(242, 211, 67)
    private val store = TranscriptStore()
    private lateinit var controller: ConversationController
    private lateinit var models: AppModels
    private lateinit var status: TextView
    private lateinit var hint: TextView
    private lateinit var direction: Spinner
    private lateinit var sensitivity: Spinner
    private lateinit var speak: Switch
    private lateinit var importButton: Button
    private lateinit var loadButton: Button
    private lateinit var startButton: Button
    private lateinit var cancelButton: Button
    private lateinit var textButton: Button
    private lateinit var replayButton: Button
    private lateinit var exportButton: Button
    private lateinit var input: EditText
    private lateinit var level: ProgressBar
    private lateinit var list: ListView
    private lateinit var adapter: Captions
    private var pendingExport: String? = null
    private var destroyed = false
    private var busy = false
    private var listening = false
    private var ready = false
    private var workingEpoch = 0L
    private val preferences by lazy { getSharedPreferences("preferences", MODE_PRIVATE) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        models = AppModels(this)
        controller = ConversationController(this, models) { event ->
            runOnUiThread { if (!destroyed) receive(event) }
        }
        buildUi()
        status.text = if (models.importer.ready()) "已找到本地模型，请加载。" else "首次使用：导入离线模型包，再加载模型。"
        renderControls()
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun label(value: String, size: Float = 14f, color: Int = ink) = TextView(this).apply {
        text = value; textSize = size; setTextColor(color)
        setPadding(0, dp(4), 0, dp(4))
    }
    private fun button(value: String, primary: Boolean = false, action: () -> Unit) = Button(this).apply {
        text = value; isAllCaps = false; textSize = 14f; minHeight = dp(48)
        setTextColor(if (primary) this@MainActivity.background else ink)
        backgroundTintList = ColorStateList.valueOf(if (primary) yellow else surface)
        setOnClickListener { attempt(action) }
    }
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun row(parent: LinearLayout, vararg children: View) {
        val line = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        children.forEachIndexed { index, child ->
            line.addView(child, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                if (index > 0) marginStart = dp(8)
            })
        }
        parent.addView(line)
    }
    private fun choose(values: List<String>, selection: Int) = Spinner(this).apply {
        adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, values)
        minimumHeight = dp(48)
        setSelection(selection)
    }
    private fun buildUi() {
        val outer = column().apply { setBackgroundColor(this@MainActivity.background) }
        // API 35 edge-to-edge: respect system bars, cutouts, and the on-screen keyboard.
        outer.setOnApplyWindowInsetsListener { view, insets ->
            @Suppress("DEPRECATION")
            view.setPadding(dp(16) + insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                dp(16) + insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            insets
        }
        val header = column()
        header.addView(label("粤普随译", 26f).apply { setTypeface(typeface, Typeface.BOLD) })
        header.addView(label("Android 开发预览 · 全程本地处理", 13f, yellow))
        importButton = button("导入模型包") { selectPack() }
        loadButton = button("加载模型") { controller.load(selectedDirection()) }
        row(header, importButton, loadButton)
        direction = choose(Direction.entries.map { it.label }, preferences.getInt("direction", 0).coerceIn(0, 1))
        sensitivity = choose(listOf("标准 · 嘈杂环境", "灵敏 · 手机外放"),
            if (Sensitivity.fromKey(preferences.getString("sensitivity", null)) == Sensitivity.STANDARD) 0 else 1)
        row(header, direction, sensitivity)
        val selected = object : AdapterView.OnItemSelectedListener {
            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                preferences.edit().putInt("direction", direction.selectedItemPosition)
                    .putString("sensitivity", selectedSensitivity().key).apply()
            }
        }
        direction.onItemSelectedListener = selected
        sensitivity.onItemSelectedListener = selected
        speak = Switch(this).apply {
            text = "自动播报译文"; setTextColor(ink); minHeight = dp(48)
            isChecked = preferences.getBoolean("speak", true)
            setOnCheckedChangeListener { _, value -> preferences.edit().putBoolean("speak", value).apply() }
        }
        header.addView(speak)
        header.addView(label("播报时暂停收音，避免回声；背景人声仍可能被识别。", 12f, muted))
        status = label("", 14f, yellow).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        level = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100; progressTintList = ColorStateList.valueOf(yellow)
            contentDescription = "麦克风音量"
        }
        startButton = button("开始收音", true) {
            if (listening) controller.finishCapture() else beginCapture()
        }
        cancelButton = button("停止处理") { store.cancel(); controller.cancel() }
        // Scrollable controls remain reachable on small screens and at large font sizes.
        val controls = ScrollView(this).apply { isFillViewport = false; addView(header) }
        outer.addView(controls, LinearLayout.LayoutParams(-1, 0, .65f))
        outer.addView(status)
        outer.addView(level, LinearLayout.LayoutParams(-1, dp(5)))
        val captionsPanel = column()
        val title = label("对话字幕", 16f).apply { setTypeface(typeface, Typeface.BOLD) }
        captionsPanel.addView(title)
        hint = label("字幕将在这里出现。\n建议先用短句测试，再开始连续对话。", 14f, muted)
        captionsPanel.addView(hint)
        adapter = Captions()
        list = ListView(this).apply {
            adapter = this@MainActivity.adapter; dividerHeight = dp(8)
            setSelector(android.R.color.transparent)
            emptyView = hint
            setOnItemClickListener { _, _, position, _ ->
                val caption = this@MainActivity.adapter.rows[position]
                if (caption.targetFinal && !busy) controller.replay(caption.target, if (caption.sourceLanguage == "yue") "zh" else "yue")
            }
        }
        captionsPanel.addView(list, LinearLayout.LayoutParams(-1, 0, 1f))
        outer.addView(captionsPanel, LinearLayout.LayoutParams(-1, 0, 1f))
        row(outer, startButton, cancelButton)
        input = EditText(this).apply {
            hint = "输入短句测试离线翻译（最多 240 字）"
            contentDescription = "待翻译短句"
            setTextColor(ink); setHintTextColor(muted); textSize = 15f
            filters = arrayOf(InputFilter.LengthFilter(240)); setSingleLine(true)
        }
        outer.addView(input)
        textButton = button("翻译短句") {
            val value = input.text.toString().trim()
            require(value.isNotEmpty()) { "请先输入短句。" }
            val epoch = beginTranscript()
            controller.text(epoch, value, selectedDirection(), speak.isChecked)
        }
        replayButton = button("重播译音") {
            val caption = store.snapshot().lastOrNull { it.targetFinal } ?: return@button
            controller.replay(caption.target, if (caption.sourceLanguage == "yue") "zh" else "yue")
        }
        exportButton = button("导出字幕") { export() }
        row(outer, textButton, replayButton, exportButton)
        setContentView(outer)
        outer.requestApplyInsets()
    }

    private fun selectedDirection() = Direction.entries[direction.selectedItemPosition.coerceIn(0, 1)]
    private fun beginTranscript(): Long = store.begin(selectedDirection().source).also { workingEpoch = it }
    private fun selectedSensitivity() = if (sensitivity.selectedItemPosition == 1) Sensitivity.SENSITIVE else Sensitivity.STANDARD
    private fun attempt(action: () -> Unit) {
        try { action() } catch (error: Exception) { showError(error.message ?: "操作未完成，请重试。") }
    }
    private fun showError(text: String) { status.text = text; status.setTextColor(Color.rgb(255, 167, 154)) }

    private fun beginCapture() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 10)
            return
        }
        val epoch = beginTranscript()
        controller.start(epoch, selectedDirection(), selectedSensitivity(), speak.isChecked)
    }
    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code, permissions, results)
        if (code == 10) {
            if (results.firstOrNull() == PackageManager.PERMISSION_GRANTED && !busy && ready && hasWindowFocus()) attempt { beginCapture() }
            else showError("未启用麦克风。可使用短句翻译；收音需要在系统设置中允许麦克风。")
        }
    }

    private fun receive(event: SessionEvent) {
        when (event) {
            is SessionEvent.State -> {
                busy = event.busy; listening = event.listening; ready = event.ready
                status.text = event.text; status.setTextColor(yellow)
                if (listening) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else { window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON); level.progress = 0 }
                renderControls()
                adapter.notifyDataSetChanged()
            }
            is SessionEvent.Source -> if (store.source(event.epoch, event.block, event.version, event.text, event.final)) refreshCaptions()
            is SessionEvent.Target -> if (store.translation(event.epoch, event.block, event.version, event.text, event.preview)) refreshCaptions()
            is SessionEvent.Level -> if (listening) level.progress = event.value
            is SessionEvent.Error -> showError(event.text)
            is SessionEvent.Finished -> refreshCaptions()
        }
    }
    private fun renderControls() {
        importButton.isEnabled = !busy; loadButton.isEnabled = !busy && models.importer.ready()
        direction.isEnabled = !busy; sensitivity.isEnabled = !busy; speak.isEnabled = !busy
        input.isEnabled = !busy; textButton.isEnabled = ready && !busy
        startButton.isEnabled = ready && (!busy || listening)
        startButton.text = if (listening) "结束收音" else if (busy) "正在处理…" else "开始收音"
        cancelButton.isEnabled = busy
        replayButton.isEnabled = ready && !busy && store.snapshot().any { it.targetFinal }
        exportButton.isEnabled = store.snapshot().isNotEmpty()
    }
    private fun refreshCaptions() {
        val follow = adapter.count == 0 || list.lastVisiblePosition >= adapter.count - 2
        adapter.rows = store.snapshot(); adapter.notifyDataSetChanged()
        if (follow && adapter.count > 0) list.setSelection(adapter.count - 1)
        renderControls()
    }

    private fun selectPack() {
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE); type = "application/zip"
            putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/zip", "application/octet-stream", "application/x-zip-compressed"))
        }, 20)
    }
    private fun export() {
        pendingExport = store.snapshot().joinToString("\n\n") {
            val from = if (it.sourceLanguage == "yue") "粤语" else "普通话"
            val to = if (it.sourceLanguage == "yue") "普通话" else "粤语"
            "$from${if (it.final) "" else "（草稿）"}：${it.source}\n$to${if (it.targetFinal) "" else "（待确认）"}：${it.target}"
        }
        startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE); type = "text/plain"
            putExtra(Intent.EXTRA_TITLE, "粤普字幕-${SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(Date())}.txt")
        }, 30)
    }
    @Deprecated("Platform activity result API is used to keep the app free of UI framework dependencies.")
    override fun onActivityResult(code: Int, result: Int, data: Intent?) {
        super.onActivityResult(code, result, data)
        if (result != RESULT_OK || data?.data == null) { if (code == 30) pendingExport = null; return }
        val uri = data.data!!
        if (code == 20) {
            val install = { attempt { controller.importPack { checkNotNull(contentResolver.openInputStream(uri)) } }; Unit }
            if (models.importer.ready()) AlertDialog.Builder(this).setTitle("替换离线模型？")
                .setMessage("会先完整校验新模型。导入失败时保留原模型；对话字幕不受影响。")
                .setNegativeButton("取消", null).setPositiveButton("导入") { _, _ -> install() }.show()
            else install()
        } else if (code == 30) {
            val value = pendingExport; pendingExport = null
            if (value != null) attempt {
                contentResolver.openOutputStream(uri, "wt").use { output ->
                    checkNotNull(output) { "无法写入所选位置。" }.write(value.toByteArray(Charsets.UTF_8))
                }
                Toast.makeText(this, "字幕已导出", Toast.LENGTH_SHORT).show()
            }
        }
    }
    override fun onStop() {
        if (busy) { store.cancel(); controller.cancel() }
        super.onStop()
    }
    override fun onDestroy() { destroyed = true; controller.close(); super.onDestroy() }

    private inner class Captions : BaseAdapter() {
        var rows: List<Caption> = emptyList()
        override fun getCount() = rows.size
        override fun getItem(position: Int) = rows[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val item = rows[position]
            val card = (convertView as? LinearLayout) ?: column().apply {
                setPadding(dp(12), dp(8), dp(12), dp(8))
                background = GradientDrawable().apply { setColor(surface); cornerRadius = dp(10).toFloat() }
                addView(label("", 12f, muted)); addView(label("", 16f)); addView(label("", 18f, yellow))
            }
            (card.getChildAt(0) as TextView).text = getString(R.string.caption_heading,
                if (item.sourceLanguage == "yue") "粤语 → 普通话" else "普通话 → 粤语",
                if (item.targetFinal) "已确认 · 点按重播"
                else if (busy && item.epoch == workingEpoch) "识别／翻译中" else "未确认 · 已停止")
            (card.getChildAt(1) as TextView).apply { text = item.source; setTextColor(if (item.final) ink else muted) }
            (card.getChildAt(2) as TextView).apply { text = item.target.ifBlank { "等待译文…" }; setTextColor(if (item.targetFinal) yellow else muted) }
            return card
        }
    }
}
