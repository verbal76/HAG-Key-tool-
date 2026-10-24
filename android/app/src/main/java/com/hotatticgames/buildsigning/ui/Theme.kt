package com.hotatticgames.buildsigning.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

object Palette {
    val bg = Color(0xFF16181D)
    val panel = Color(0xFF1E2128)
    val panelAlt = Color(0xFF252932)
    val border = Color(0xFF323745)
    val text = Color(0xFFE6E8EE)
    val muted = Color(0xFF9AA1B2)
    val accent = Color(0xFFE8833A)
    val accentText = Color(0xFF1A1206)
    val success = Color(0xFF4CC38A)
    val warning = Color(0xFFF2C14E)
    val error = Color(0xFFF2685E)
    val info = Color(0xFF6AA8FF)
}

private val scheme = darkColorScheme(
    primary = Palette.accent,
    onPrimary = Palette.accentText,
    secondary = Palette.info,
    background = Palette.bg,
    onBackground = Palette.text,
    surface = Palette.panel,
    onSurface = Palette.text,
    surfaceVariant = Palette.panelAlt,
    onSurfaceVariant = Palette.muted,
    surfaceContainer = Palette.panel,
    surfaceContainerHigh = Palette.panelAlt,
    surfaceContainerLow = Palette.panel,
    outline = Palette.border,
    error = Palette.error,
)

@Composable
fun AppTheme(content: @Composable () -> Unit) = MaterialTheme(colorScheme = scheme, content = content)
