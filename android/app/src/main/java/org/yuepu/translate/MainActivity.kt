package org.yuepu.translate

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.app.Dialog
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.InputFilter
import android.text.InputType
import android.text.TextUtils
import android.text.TextWatcher
import android.view.ContextThemeWrapper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import org.yuepu.translate.core.Caption
import org.yuepu.translate.core.Direction
import org.yuepu.translate.core.Sensitivity
import org.yuepu.translate.core.TranscriptStore
import org.yuepu.translate.engine.AppModels
import org.yuepu.translate.engine.ConversationController
import org.yuepu.translate.engine.SessionEvent

class MainActivity : Activity() {
    private val preferences by lazy { getSharedPreferences("preferences", MODE_PRIVATE) }
    private lateinit var ui: MobileUi
    private lateinit var models: AppModels
    private lateinit var controller: ConversationController
    private lateinit var history: SessionHistory
    private val store = TranscriptStore()
    private val handler = Handler(Looper.getMainLooper())
    private val saveTask = Runnable { flushHistory() }
    private var historyDirty = false
    private var saveQueued = false
    private var sessionId = UUID.randomUUID().toString()
    private var sessions = emptyList<SavedSession>()
    private val drafts = mutableMapOf<String, String>()

    private lateinit var pane: LinearLayout
    private lateinit var toolbar: LinearLayout
    private lateinit var composerOptions: LinearLayout
    private lateinit var captionTools: LinearLayout
    private lateinit var empty: ScrollView
    private lateinit var onboarding: LinearLayout
    private lateinit var input: EditText
    private lateinit var directionButton: Button
    private lateinit var optionsButton: Button
    private lateinit var mic: Button
    private lateinit var send: Button
    private lateinit var settingsButton: Button
    private lateinit var sessionsButton: Button
    private lateinit var exportButton: Button
    private lateinit var clearButton: Button
    private lateinit var cancelButton: Button
    private lateinit var status: TextView
    private lateinit var level: ProgressBar
    private lateinit var captions: ListView
    private lateinit var adapter: Captions
    private var rail: HistoryPanel? = null
    private var currentSheet: Dialog? = null

    private var statusMessage = ""
    private var statusError = false
    private var pendingExport: String? = null
    private var exportSession: String? = null
    private var afterLoad: (() -> Unit)? = null
    private var importing = false
    private var busy = false
    private var listening = false
    private var ready = false
    private var packReady = false
    private var resumed = false
    private var captureAfterPermission = false
    private var destroyed = false
    private var keyboardVisible = false
    private var compactKeyboard = false
    private var inputLevel = 0
    private var workingEpoch = 0L

    private val widthDp get() = resources.configuration.screenWidthDp
    private val wide get() = widthDp >= 720
    private val paired get() = widthDp >= 900
    private val appearance get() = preferences.getString("appearance", "dark") ?: "dark"
    private val light get() = when (appearance) {
        "light" -> true
        "system" -> resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK !=
            Configuration.UI_MODE_NIGHT_YES
        else -> false
    }
    private val themeResource get() = if (light) R.style.AppThemeLight else R.style.AppTheme
    private fun dp(value: Int) = ui.dp(value)
    private fun direction() = Direction.entries[preferences.getInt("direction", 0).coerceIn(0, 1)]
    private fun sensitivity() = Sensitivity.fromKey(preferences.getString("sensitivity", null))
    private fun autoSpeak() = preferences.getBoolean("speak", true)

    override fun onCreate(savedInstanceState: Bundle?) {
        setTheme(themeResource)
        super.onCreate(savedInstanceState)
        history = SessionHistory(this)
        sessionId = savedInstanceState?.getString("session") ?: sessionId
        exportSession = savedInstanceState?.getString("exportSession")
        if (savedInstanceState != null) attempt { store.restore(history.load(sessionId)) }
        models = AppModels(this)
        packReady = models.importer.ready()
        controller = ConversationController(this, models) { event ->
            runOnUiThread { if (!destroyed) receive(event) }
        }
        refreshHistory()
        buildUi(savedInstanceState?.getString("draft").orEmpty())
    }

    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun row() = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
    private fun weighted() = LinearLayout.LayoutParams(0, -2, 1f)

    private fun buildUi(draft: String) {
        val readingOlder = ::captions.isInitialized && adapter.count > 0 &&
            captions.lastVisiblePosition < adapter.count - 1
        val rowAtTop = if (readingOlder) captions.firstVisiblePosition else 0
        val rowOffset = if (readingOlder) captions.getChildAt(0)?.top ?: 0 else 0
        ui = MobileUi(this, light)
        styleSystemBars()
        val outer = row().apply {
            gravity = Gravity.TOP
            setBackgroundColor(ui.background)
            setOnApplyWindowInsetsListener { view, insets ->
                if (Build.VERSION.SDK_INT >= 30) {
                    val safe = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                    val ime = insets.getInsets(WindowInsets.Type.ime())
                    val bottom = maxOf(safe.bottom, ime.bottom)
                    view.setPadding(safe.left, safe.top, safe.right, bottom)
                    updateKeyboard(
                        insets.isVisible(WindowInsets.Type.ime()),
                        windowManager.currentWindowMetrics.bounds.height() - safe.top - bottom,
                    )
                }
                insets
            }
            if (Build.VERSION.SDK_INT < 30) addOnLayoutChangeListener { _, _, top, _, bottom, _, _, _, _ ->
                val available = bottom - top
                val visible = resources.displayMetrics.heightPixels - available > dp(120)
                updateKeyboard(visible, available)
            }
        }
        rail = if (wide) HistoryPanel().also { panel ->
            outer.addView(panel.view, LinearLayout.LayoutParams(dp(232), -1))
            outer.addView(View(this).apply { setBackgroundColor(ui.border) },
                LinearLayout.LayoutParams(dp(1), -1))
        } else null
        pane = column().apply {
            val gutter = dp(if (wide) 24 else 16)
            setPadding(gutter, dp(4), gutter, dp(8))
            isFocusableInTouchMode = true
        }
        outer.addView(pane, LinearLayout.LayoutParams(0, -1, 1f))
        buildHeader()
        buildCaptionPane()
        buildComposer(draft)
        setContentView(outer)
        pane.requestFocus()
        outer.requestApplyInsets()
        refreshCaptions()
        if (readingOlder && adapter.count > rowAtTop) captions.setSelectionFromTop(rowAtTop, rowOffset)
    }

    private fun updateKeyboard(visible: Boolean, available: Int) {
        val compact = visible && available < dp(300)
        if (keyboardVisible == visible && compactKeyboard == compact) return
        keyboardVisible = visible
        compactKeyboard = compact
        renderControls()
    }

    private fun buildHeader() {
        toolbar = row().apply { minimumHeight = dp(52) }
        toolbar.addView(ui.text("粤普随译", 21f, strong = true), weighted())
        sessionsButton = ui.button("会话", ButtonKind.Quiet) { showHistory() }
        settingsButton = ui.button("设置", ButtonKind.Quiet) { showSettings() }
        toolbar.addView(sessionsButton)
        toolbar.addView(settingsButton)
        pane.addView(toolbar)
    }

    private fun buildCaptionPane() {
        captionTools = row()
        captionTools.addView(ui.text("字幕", 17f, strong = true), weighted())
        exportButton = ui.button("导出", ButtonKind.Quiet) { attempt { export() } }
        clearButton = ui.button("清空", ButtonKind.Quiet) { confirmClear() }
        captionTools.addView(exportButton)
        captionTools.addView(clearButton)
        pane.addView(captionTools)

        val workarea = FrameLayout(this)
        adapter = Captions()
        captions = ListView(this).apply {
            adapter = this@MainActivity.adapter
            divider = ColorDrawable(ui.border)
            dividerHeight = dp(1)
            setOnItemClickListener { _, _, position, _ ->
                val item = this@MainActivity.adapter.rows.getOrNull(position) ?: return@setOnItemClickListener
                if (item.targetFinal && !busy && packReady) attempt {
                    withReady { controller.replay(item.target, if (item.sourceLanguage == "yue") "zh" else "yue") }
                }
            }
        }
        workarea.addView(captions, FrameLayout.LayoutParams(-1, -1))
        empty = ScrollView(this).apply { isFillViewport = true }
        val welcome = column().apply {
            gravity = Gravity.CENTER
            setPadding(dp(12), dp(20), dp(12), dp(20))
        }
        welcome.addView(ImageView(this).apply {
            setImageResource(R.drawable.yuepu_mark)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(dp(64), dp(64)))
        welcome.addView(ui.text("粤普随译", 28f, strong = true).apply {
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, 0)
        })
        onboarding = column().apply {
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, 0)
            addView(ui.text("导入离线模型包后即可翻译", 15f, ui.muted).apply { gravity = Gravity.CENTER })
            addView(ui.button("导入离线模型包", ButtonKind.Primary) { attempt { selectPack() } },
                LinearLayout.LayoutParams(-2, -2).apply { topMargin = dp(10) })
        }
        welcome.addView(onboarding)
        empty.addView(welcome)
        workarea.addView(empty, FrameLayout.LayoutParams(-1, -1))
        pane.addView(workarea, LinearLayout.LayoutParams(-1, 0, 1f))
    }

    private fun buildComposer(draft: String) {
        val composer = column().apply {
            background = ui.shape(ui.field, 16, ui.border)
            setPadding(dp(10), dp(8), dp(10), dp(8))
        }
        input = EditText(this).apply {
            contentDescription = "待翻译文字"
            hint = "输入短句，或开始收音"
            setHintTextColor(ui.muted)
            setTextColor(ui.ink)
            textSize = 19f
            background = null
            gravity = Gravity.TOP
            setPadding(dp(6), dp(5), dp(6), dp(5))
            minHeight = dp(52)
            maxLines = 3
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            imeOptions = EditorInfo.IME_ACTION_SEND
            filters = arrayOf(InputFilter.LengthFilter(240))
            setText(draft)
            setOnEditorActionListener { _, action, _ ->
                if (action != EditorInfo.IME_ACTION_SEND || !send.isEnabled) false
                else { attempt { translateInput() }; true }
            }
        }
        composer.addView(input, LinearLayout.LayoutParams(-1, -2))
        composerOptions = row()
        directionButton = ui.button(direction().label, ButtonKind.Outline) { showDirection() }
        directionButton.contentDescription = "翻译方向：${direction().label}"
        optionsButton = ui.button("收音选项", ButtonKind.Quiet) { showRecordingOptions() }
        composerOptions.addView(directionButton, weighted())
        composerOptions.addView(optionsButton, LinearLayout.LayoutParams(-2, -2).apply { marginStart = dp(4) })
        val actions = row()
        mic = ui.button("开始收音", ButtonKind.Secondary) {
            attempt { if (listening) controller.finishCapture() else requestCapture() }
        }
        send = ui.button("翻译", ButtonKind.Primary) { attempt { translateInput() } }
        actions.addView(mic, weighted())
        actions.addView(send, weighted().apply { marginStart = dp(6) })
        if (widthDp >= 840) {
            composer.addView(row().apply {
                addView(composerOptions, weighted())
                addView(actions, weighted().apply { marginStart = dp(8) })
            })
        } else {
            composer.addView(composerOptions)
            composer.addView(actions, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(6) })
        }
        pane.addView(composer)

        level = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progressTintList = ColorStateList.valueOf(ui.accent)
            contentDescription = "麦克风音量"
        }
        pane.addView(level, LinearLayout.LayoutParams(-1, dp(4)).apply { topMargin = dp(6) })
        val feedback = row()
        status = ui.text("", 15f, ui.muted).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
            setPadding(dp(4), dp(6), dp(4), dp(6))
        }
        cancelButton = ui.button("取消任务", ButtonKind.Quiet) { cancelWork() }
        feedback.addView(status, weighted())
        feedback.addView(cancelButton)
        pane.addView(feedback)
        input.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) = renderControls()
            override fun afterTextChanged(s: Editable?) = Unit
        })
    }

    private fun styleSystemBars() {
        if (Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false)
            val mask = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
            window.insetsController?.setSystemBarsAppearance(if (light) mask else 0, mask)
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = if (light) {
                View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
            } else 0
        }
        if (Build.VERSION.SDK_INT < 35) {
            @Suppress("DEPRECATION")
            window.statusBarColor = ui.background
            @Suppress("DEPRECATION")
            window.navigationBarColor = ui.background
        }
    }

    private fun showSheet(
        title: String, heightDp: Int = 480, scrollable: Boolean = true,
        content: (LinearLayout, Dialog) -> Unit,
    ) {
        currentSheet?.dismiss()
        hideKeyboard()
        val dialog = Dialog(ContextThemeWrapper(this, themeResource))
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)
        val card = column().apply {
            background = ui.shape(ui.panel, 20, ui.border)
            setPadding(dp(16), dp(8), dp(16), dp(12))
        }
        val header = row()
        header.addView(ui.text(title, 21f, strong = true), weighted())
        header.addView(ui.button("关闭", ButtonKind.Quiet) { dialog.dismiss() })
        card.addView(header)
        val body = column()
        val panel = if (scrollable) ScrollView(this).apply { addView(body) } else body
        card.addView(panel, LinearLayout.LayoutParams(-1, 0, 1f))
        content(body, dialog)
        dialog.setContentView(card)
        dialog.setOnDismissListener { if (currentSheet === dialog) currentSheet = null }
        currentSheet = dialog
        dialog.show()
        val bounds = if (Build.VERSION.SDK_INT >= 30) windowManager.currentWindowMetrics.bounds else null
        val width = bounds?.width() ?: resources.displayMetrics.widthPixels
        val height = bounds?.height() ?: resources.displayMetrics.heightPixels
        dialog.window?.apply {
            setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
            setGravity(Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL)
            setLayout(minOf(dp(560), width - dp(16)), minOf(dp(heightDp), (height * .8f).toInt()))
            setDimAmount(.48f)
        }
    }

    private fun showDirection() = showSheet("翻译方向", 230) { body, dialog ->
        Direction.entries.forEach { option ->
            val selected = direction() == option
            body.addView(ui.button(
                if (selected) "✓  ${option.label}" else option.label,
                if (selected) ButtonKind.Secondary else ButtonKind.Quiet,
            ) {
                preferences.edit().putInt("direction", option.ordinal).apply()
                directionButton.text = option.label
                directionButton.contentDescription = "翻译方向：${option.label}"
                dialog.dismiss()
            }, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(6) })
        }
    }

    private fun section(body: LinearLayout, title: String) {
        body.addView(ui.text(title, 17f, strong = true).apply {
            setPadding(0, dp(14), 0, dp(6))
        })
    }

    private fun showRecordingOptions() = showSheet("收音选项", 390) { body, dialog ->
        section(body, "收音灵敏度")
        val choices = row()
        Sensitivity.entries.forEach { value ->
            val selected = value == sensitivity()
            ui.button(if (selected) "✓  ${value.label}" else value.label,
                if (selected) ButtonKind.Secondary else ButtonKind.Outline) {
                preferences.edit().putString("sensitivity", value.key).apply()
                dialog.dismiss()
            }.also { button ->
                choices.addView(button, weighted().apply {
                    if (value != Sensitivity.entries.first()) marginStart = dp(6)
                })
            }
        }
        body.addView(choices)
        body.addView(ui.text("标准适合嘈杂环境，灵敏适合较轻的声音。", 15f, ui.muted).apply {
            setPadding(0, dp(6), 0, 0)
        })
        section(body, "译音")
        body.addView(Switch(ContextThemeWrapper(this, themeResource)).apply {
            text = "自动播报译文"
            textSize = 16f
            setTextColor(ui.ink)
            minHeight = dp(48)
            isChecked = autoSpeak()
            setOnCheckedChangeListener { _, value -> preferences.edit().putBoolean("speak", value).apply() }
        })
        body.addView(ui.text("播报期间暂停收音，避免把译音再次识别。", 15f, ui.muted))
    }

    private fun showSettings() = showSheet("设置", 530) { body, dialog ->
        section(body, "外观")
        for ((key, name) in listOf("dark" to "深色", "light" to "浅色", "system" to "跟随系统")) {
            val selected = appearance == key
            body.addView(ui.button(if (selected) "✓  $name" else name,
                if (selected) ButtonKind.Secondary else ButtonKind.Quiet) {
                dialog.dismiss()
                if (!selected) {
                    val draft = input.text.toString()
                    preferences.edit().putString("appearance", key).apply()
                    setTheme(themeResource)
                    buildUi(draft)
                }
            }, LinearLayout.LayoutParams(-1, -2))
        }
        section(body, "离线模型")
        body.addView(ui.text(when {
            ready -> "本地模型已就绪"
            packReady -> "已导入，首次翻译时自动加载"
            else -> "请导入适用于 Android 的离线模型包"
        }, 15f, ui.muted))
        body.addView(ui.button(if (packReady) "替换模型包" else "导入模型包", ButtonKind.Outline) {
            dialog.dismiss()
            attempt { selectPack() }
        }, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) })
        if (packReady && !ready) {
            body.addView(ui.button("预加载模型", ButtonKind.Quiet) {
                dialog.dismiss()
                attempt { controller.load(direction()) }
            }, LinearLayout.LayoutParams(-1, -2))
        }
        section(body, "收音与播报")
        body.addView(ui.button("收音选项", ButtonKind.Outline) { showRecordingOptions() },
            LinearLayout.LayoutParams(-1, -2))
    }

    private fun showHistory() {
        refreshHistory()
        showSheet("会话历史", 560, scrollable = false) { body, dialog ->
            body.addView(HistoryPanel(heading = false, onOpen = { dialog.dismiss() }).view,
                LinearLayout.LayoutParams(-1, 0, 1f))
        }
    }

    private inner class HistoryPanel(heading: Boolean = true, onOpen: () -> Unit = {}) {
        val view = column().apply {
            setBackgroundColor(ui.panel)
            if (heading) setPadding(dp(20), dp(10), dp(16), dp(12))
        }
        private val emptyHistory = ui.text("暂无会话", 15f, ui.muted).apply {
            setPadding(dp(8), dp(12), 0, 0)
        }
        private val rows = HistoryRows()
        private val list = ListView(this@MainActivity).apply {
            adapter = rows
            divider = null
            setOnItemClickListener { _, _, position, _ ->
                val item = sessions.getOrNull(position) ?: return@setOnItemClickListener
                if (changeSession(item.id)) onOpen()
            }
        }
        private val add = ui.button("＋  新会话", ButtonKind.Secondary) {
            if (changeSession(UUID.randomUUID().toString())) onOpen()
        }

        init {
            if (heading) view.addView(ui.text("会话历史", 19f, strong = true).apply {
                setPadding(dp(8), dp(8), 0, dp(12))
            })
            view.addView(add, LinearLayout.LayoutParams(-1, -2))
            view.addView(emptyHistory)
            view.addView(list, LinearLayout.LayoutParams(-1, 0, 1f))
            refresh()
        }

        fun refresh() {
            emptyHistory.visibility = if (sessions.isEmpty()) View.VISIBLE else View.GONE
            rows.notifyDataSetChanged()
            setAvailable()
        }

        fun setAvailable() {
            add.isEnabled = !busy
            list.isEnabled = !busy
        }
    }

    private inner class HistoryRows : BaseAdapter() {
        override fun getCount() = sessions.size
        override fun getItem(position: Int) = sessions[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val item = getItem(position)
            val card = (convertView as? LinearLayout) ?: column().apply {
                minimumHeight = dp(58)
                setPadding(dp(12), dp(8), dp(12), dp(8))
                addView(ui.text("", 16f).apply {
                    maxLines = 1
                    ellipsize = TextUtils.TruncateAt.END
                })
                addView(ui.text("", 15f, ui.muted))
            }
            card.background = if (item.id == sessionId) ui.shape(ui.field, 8, ui.border) else null
            (card.getChildAt(0) as TextView).text = item.title
            val time = SimpleDateFormat("MM/dd HH:mm", Locale.getDefault()).format(Date(item.updatedAt))
            (card.getChildAt(1) as TextView).text = time
            return card
        }
    }

    private fun refreshHistory() {
        try {
            sessions = history.list()
            rail?.refresh()
        } catch (_: Exception) {
            showStatus("无法读取本机会话历史。", true)
        }
    }

    private fun flushHistory(): Boolean {
        handler.removeCallbacks(saveTask)
        saveQueued = false
        if (!historyDirty) return true
        return try {
            history.save(sessionId, store.snapshot())
            historyDirty = false
            refreshHistory()
            true
        } catch (_: Exception) {
            showStatus("本机会话保存失败。可用导出保留字幕。", true)
            false
        }
    }

    private fun changeSession(id: String): Boolean {
        if (busy || !flushHistory()) return false
        if (id == sessionId) return true
        try {
            store.restore(history.load(id))
        } catch (_: Exception) {
            showStatus("无法打开这次会话。", true)
            return false
        }
        val draft = input.text.toString()
        if (draft.isNotBlank()) drafts[sessionId] = draft else drafts.remove(sessionId)
        sessionId = id
        input.setText(drafts.remove(id).orEmpty())
        workingEpoch = 0L
        showStatus("")
        refreshCaptions(forceFollow = true)
        rail?.refresh()
        return true
    }

    private fun confirmClear() {
        if (busy || store.snapshot().isEmpty()) return
        AlertDialog.Builder(ContextThemeWrapper(this, themeResource))
            .setTitle("清空本次会话？")
            .setMessage("字幕将从本机历史中移除。")
            .setNegativeButton("取消", null)
            .setPositiveButton("清空") { _, _ -> attempt {
                history.delete(sessionId)
                handler.removeCallbacks(saveTask)
                historyDirty = false
                saveQueued = false
                store.restore(emptyList())
                workingEpoch = 0L
                showStatus("")
                refreshCaptions()
                refreshHistory()
            } }.show()
    }

    private fun withReady(action: () -> Unit) {
        if (busy || afterLoad != null) return
        require(packReady) { "请在设置中导入离线模型包。" }
        if (ready) action()
        else {
            afterLoad = action
            try {
                controller.load(direction())
            } catch (error: Exception) {
                afterLoad = null
                throw error
            }
        }
    }

    private fun translateInput() {
        val value = input.text.toString().trim()
        require(value.isNotEmpty()) { "请输入要翻译的短句。" }
        hideKeyboard()
        withReady {
            controller.text(beginTranscript(), value, direction(), autoSpeak())
            input.text.clear()
        }
    }

    private fun hideKeyboard() {
        getSystemService(InputMethodManager::class.java)?.hideSoftInputFromWindow(input.windowToken, 0)
        pane.requestFocus()
    }

    private fun beginTranscript(): Long = store.begin(direction().source).also { workingEpoch = it }

    private fun requestCapture() {
        if (busy || !packReady) return
        hideKeyboard()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQUEST_MIC)
            return
        }
        captureAfterPermission = true
        startIfForeground()
    }

    private fun startIfForeground() {
        if (!captureAfterPermission || !resumed || !hasWindowFocus() || busy) return
        captureAfterPermission = false
        attempt { withReady { controller.start(beginTranscript(), direction(), sensitivity(), autoSpeak()) } }
    }

    override fun onRequestPermissionsResult(code: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(code, permissions, results)
        if (code != REQUEST_MIC) return
        captureAfterPermission = results.firstOrNull() == PackageManager.PERMISSION_GRANTED
        if (captureAfterPermission) startIfForeground()
        else showStatus("麦克风权限未开启。仍可用输入框翻译文字。", true)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            resumeLoadedAction()
            startIfForeground()
        }
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        resumeLoadedAction()
        startIfForeground()
    }

    override fun onPause() {
        resumed = false
        super.onPause()
    }

    private fun cancelWork() {
        afterLoad = null
        captureAfterPermission = false
        store.cancel()
        controller.cancel()
    }

    private fun resumeLoadedAction() {
        val action = afterLoad ?: return
        if (destroyed || busy) return
        if (ready && (!resumed || !hasWindowFocus())) return
        afterLoad = null
        if (ready) attempt(action)
        renderControls()
    }

    private fun receive(event: SessionEvent) {
        when (event) {
            is SessionEvent.State -> {
                busy = event.busy
                listening = event.listening
                ready = event.ready
                if (listening) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else {
                    window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    inputLevel = 0
                }
                statusError = statusError && statusMessage == event.text
                statusMessage = event.text
                if (!busy) {
                    store.cancel()
                    if (importing) {
                        importing = false
                        packReady = models.importer.ready()
                    }
                    flushHistory()
                    if (afterLoad != null) handler.post(::resumeLoadedAction)
                }
                refreshCaptions()
            }
            is SessionEvent.Source -> if (
                store.source(event.epoch, event.block, event.version, event.text, event.final)
            ) captionsChanged()
            is SessionEvent.Target -> if (
                store.translation(event.epoch, event.block, event.version, event.text, event.preview)
            ) captionsChanged()
            is SessionEvent.Level -> {
                inputLevel = event.value
                if (listening) level.progress = inputLevel
            }
            is SessionEvent.Error -> showStatus(event.text, true)
            is SessionEvent.Finished -> flushHistory()
        }
    }

    private fun captionsChanged() {
        historyDirty = true
        if (!saveQueued) {
            saveQueued = true
            handler.postDelayed(saveTask, 850)
        }
        refreshCaptions()
    }

    private fun renderControls() {
        if (!::status.isInitialized) return
        val hasCaptions = adapter.count > 0
        val idle = !busy && afterLoad == null
        toolbar.visibility = if (compactKeyboard) View.GONE else View.VISIBLE
        composerOptions.visibility = if (compactKeyboard) View.GONE else View.VISIBLE
        empty.visibility = if (hasCaptions || keyboardVisible) View.GONE else View.VISIBLE
        captions.visibility = if (hasCaptions) View.VISIBLE else View.GONE
        onboarding.visibility = if (!packReady && idle) View.VISIBLE else View.GONE
        captionTools.visibility = if (hasCaptions && !keyboardVisible) View.VISIBLE else View.GONE
        sessionsButton.visibility = if (wide) View.GONE else View.VISIBLE
        sessionsButton.isEnabled = idle
        settingsButton.isEnabled = idle
        directionButton.isEnabled = idle
        optionsButton.isEnabled = idle
        exportButton.isEnabled = idle
        clearButton.isEnabled = idle
        input.isEnabled = idle
        val lines = if (compactKeyboard) 1 else 3
        if (input.maxLines != lines) input.maxLines = lines
        mic.visibility = if (compactKeyboard) View.GONE else View.VISIBLE
        mic.isEnabled = packReady && (idle || listening)
        mic.text = if (listening) "结束收音" else "开始收音"
        send.isEnabled = packReady && idle && input.text.isNotBlank()
        cancelButton.visibility = if (busy || !idle) View.VISIBLE else View.GONE
        level.visibility = if (listening) View.VISIBLE else View.GONE
        level.progress = if (listening) inputLevel else 0
        val message = when {
            statusMessage.isNotBlank() -> statusMessage
            hasCaptions && !packReady -> "请在设置中导入离线模型包。"
            else -> ""
        }
        if (status.text.toString() != message) status.text = message
        status.setTextColor(if (statusError) ui.error else ui.muted)
        status.visibility = if (message.isBlank()) View.GONE else View.VISIBLE
        rail?.setAvailable()
    }

    private fun refreshCaptions(forceFollow: Boolean = false) {
        val follow = forceFollow || adapter.count == 0 || captions.lastVisiblePosition >= adapter.count - 2
        adapter.rows = store.snapshot()
        adapter.notifyDataSetChanged()
        if (follow && adapter.count > 0) captions.setSelection(adapter.count - 1)
        renderControls()
    }

    private fun showStatus(message: String, error: Boolean = false) {
        statusMessage = message
        statusError = error
        renderControls()
    }

    private fun attempt(action: () -> Unit) {
        try { action() }
        catch (error: Exception) { showStatus(error.message ?: "操作未完成，请重试。", true) }
    }

    private fun selectPack() {
        if (busy) return
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "application/zip"
            putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/zip", "application/octet-stream", "application/x-zip-compressed"))
        }, REQUEST_PACK)
    }

    private fun exportText(rows: List<Caption>) = rows.joinToString("\n\n") {
        val from = if (it.sourceLanguage == "yue") "粤语" else "普通话"
        val to = if (it.sourceLanguage == "yue") "普通话" else "粤语"
        "$from${if (it.final) "" else "（草稿）"}：${it.source}\n$to${if (it.targetFinal) "" else "（待确认）"}：${it.target}"
    }

    private fun export() {
        if (busy) return
        val rows = store.snapshot()
        if (rows.isEmpty()) return
        pendingExport = exportText(rows)
        exportSession = sessionId
        flushHistory()
        startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "text/plain"
            putExtra(Intent.EXTRA_TITLE, "粤普字幕-${SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(Date())}.txt")
        }, REQUEST_EXPORT)
    }

    @Deprecated("Uses Android's document picker without additional UI framework dependencies.")
    override fun onActivityResult(code: Int, result: Int, data: Intent?) {
        super.onActivityResult(code, result, data)
        val uri = data?.data
        if (code == REQUEST_EXPORT) {
            val fromSession = exportSession
            val snapshot = pendingExport
            pendingExport = null
            exportSession = null
            if (result == RESULT_OK && uri != null) attempt {
                val value = snapshot ?: fromSession?.let { exportText(history.load(it)) }.orEmpty()
                require(value.isNotEmpty()) { "没有可导出的字幕。" }
                contentResolver.openOutputStream(uri, "wt").use { output ->
                    checkNotNull(output) { "无法写入所选位置。" }.write(value.toByteArray(Charsets.UTF_8))
                }
                Toast.makeText(this, "字幕已导出", Toast.LENGTH_SHORT).show()
            }
        } else if (code == REQUEST_PACK && result == RESULT_OK && uri != null) {
            val install = {
                attempt {
                    controller.importPack { checkNotNull(contentResolver.openInputStream(uri)) }
                    importing = true
                }
            }
            if (packReady) AlertDialog.Builder(ContextThemeWrapper(this, themeResource))
                .setTitle("替换离线模型？")
                .setMessage("导入时会先完整校验新模型。校验失败会保留原模型。")
                .setNegativeButton("取消", null)
                .setPositiveButton("导入") { _, _ -> install() }.show()
            else install()
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        flushHistory()
        outState.putString("session", sessionId)
        outState.putString("draft", input.text.toString())
        outState.putString("exportSession", exportSession)
        super.onSaveInstanceState(outState)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        currentSheet?.dismiss()
        val draft = input.text.toString()
        keyboardVisible = false
        compactKeyboard = false
        buildUi(draft)
    }

    override fun onStop() {
        captureAfterPermission = false
        if (busy || afterLoad != null) cancelWork()
        flushHistory()
        super.onStop()
    }

    override fun onDestroy() {
        destroyed = true
        currentSheet?.dismiss()
        handler.removeCallbacksAndMessages(null)
        controller.close()
        history.close()
        super.onDestroy()
    }

    private inner class Captions : BaseAdapter() {
        var rows: List<Caption> = emptyList()
        override fun getCount() = rows.size
        override fun getItem(position: Int) = rows[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View =
            ((convertView as? CaptionRow) ?: CaptionRow()).apply { bind(getItem(position)) }
    }

    private inner class CaptionRow : LinearLayout(this@MainActivity) {
        private val info = ui.text("", 15f, ui.muted)
        private val source = ui.text("", 18f)
        private val target = ui.text("", 20f, strong = true)

        init {
            orientation = VERTICAL
            setPadding(dp(4), dp(12), dp(4), dp(14))
            info.setPadding(0, 0, 0, dp(5))
            target.setPadding(0, if (paired) 0 else dp(4), 0, 0)
            addView(info)
            if (paired) addView(row().apply {
                gravity = Gravity.TOP
                addView(source, weighted())
                addView(target, weighted().apply { marginStart = dp(20) })
            }) else {
                addView(source)
                addView(target)
            }
        }

        fun bind(item: Caption) {
            val language = if (item.sourceLanguage == "yue") "粤语 → 普通话" else "普通话 → 粤语"
            val state = when {
                item.targetFinal -> "已确认"
                busy && item.epoch == workingEpoch -> "翻译中"
                else -> "未确认"
            }
            info.text = "$language · $state"
            source.text = item.source
            target.text = item.target.ifBlank { if (state == "翻译中") "等待译文…" else "暂无译文" }
            source.setTextColor(if (item.final) ui.ink else ui.muted)
            target.setTextColor(if (item.targetFinal) ui.ink else ui.muted)
            contentDescription = "$language，$state，原文：${item.source}，译文：${item.target}" +
                if (item.targetFinal && !busy && packReady) "，点按重播" else ""
        }
    }

    private companion object {
        const val REQUEST_MIC = 10
        const val REQUEST_PACK = 20
        const val REQUEST_EXPORT = 30
    }
}
