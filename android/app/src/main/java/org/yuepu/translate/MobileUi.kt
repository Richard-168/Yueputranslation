package org.yuepu.translate

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.graphics.drawable.StateListDrawable
import android.view.Gravity
import android.widget.Button
import android.widget.TextView
import kotlin.math.roundToInt

internal enum class ButtonKind { Primary, Secondary, Quiet, Outline }

internal class MobileUi(val context: Context, val light: Boolean) {
    val background = if (light) Color.WHITE else Color.rgb(25, 25, 25)
    val panel = if (light) Color.rgb(245, 245, 245) else Color.rgb(32, 32, 32)
    val field = if (light) Color.WHITE else Color.rgb(36, 36, 36)
    val ink = if (light) Color.rgb(32, 32, 32) else Color.rgb(242, 242, 242)
    val muted = if (light) Color.rgb(97, 97, 97) else Color.rgb(171, 171, 171)
    val border = if (light) Color.rgb(136, 136, 136) else Color.rgb(116, 116, 116)
    val error = if (light) Color.rgb(163, 42, 37) else Color.rgb(255, 180, 174)
    val accent = if (light) Color.rgb(36, 36, 36) else Color.rgb(234, 234, 234)
    val onAccent = if (light) Color.WHITE else Color.rgb(25, 25, 25)
    private val raised = if (light) Color.rgb(238, 238, 238) else Color.rgb(43, 43, 43)
    private val disabledInk = if (light) Color.rgb(104, 104, 104) else Color.rgb(160, 160, 160)

    fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).roundToInt()

    fun shape(color: Int, radius: Int = 12, stroke: Int? = null): GradientDrawable =
        GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(radius).toFloat()
            if (stroke != null) setStroke(dp(1).coerceAtLeast(1), stroke)
        }

    fun text(
        value: String,
        size: Float = 16f,
        color: Int = ink,
        strong: Boolean = false,
    ): TextView = TextView(context).apply {
        text = value
        textSize = size
        setTextColor(color)
        includeFontPadding = false
        if (strong) setTypeface(typeface, Typeface.BOLD)
    }

    fun button(
        value: String,
        kind: ButtonKind = ButtonKind.Secondary,
        action: () -> Unit,
    ): Button = Button(context).apply {
        text = value
        textSize = 15f
        isAllCaps = false
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        gravity = Gravity.CENTER
        minHeight = dp(48)
        minimumHeight = dp(48)
        minWidth = dp(48)
        minimumWidth = dp(48)
        includeFontPadding = false
        stateListAnimator = null
        backgroundTintList = null

        val fill = when (kind) {
            ButtonKind.Primary -> accent
            ButtonKind.Secondary -> raised
            ButtonKind.Quiet, ButtonKind.Outline -> Color.TRANSPARENT
        }
        val labelColor = if (kind == ButtonKind.Primary) onAccent else ink
        val outline = if (kind == ButtonKind.Outline) border else null
        val disabled = intArrayOf(-android.R.attr.state_enabled)
        val focused = intArrayOf(android.R.attr.state_focused)
        val normal = intArrayOf()
        setTextColor(ColorStateList(arrayOf(disabled, normal), intArrayOf(disabledInk, labelColor)))

        val surface = StateListDrawable().apply {
            addState(disabled, shape(if (kind == ButtonKind.Primary) raised else fill, stroke = outline))
            addState(focused, shape(fill, stroke = if (kind == ButtonKind.Primary) border else ink))
            addState(normal, shape(fill, stroke = outline))
        }
        val ripple = Color.argb(45, Color.red(labelColor), Color.green(labelColor), Color.blue(labelColor))
        background = RippleDrawable(ColorStateList.valueOf(ripple), surface, shape(Color.WHITE))
        setPaddingRelative(dp(12), dp(8), dp(12), dp(8))
        setOnClickListener { action() }
    }
}
