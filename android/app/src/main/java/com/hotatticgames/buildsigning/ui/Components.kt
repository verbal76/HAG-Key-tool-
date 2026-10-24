package com.hotatticgames.buildsigning.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.hotatticgames.buildsigning.core.ERROR
import com.hotatticgames.buildsigning.core.Issue
import kotlinx.coroutines.delay

@Composable
fun ScreenColumn(title: String, subtitle: String = "", content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
        if (subtitle.isNotEmpty()) Muted(subtitle)
        content()
    }
}

@Composable
fun Section(title: String = "", subtitle: String = "", modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Card(
        modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Palette.panel),
        border = BorderStroke(1.dp, Palette.border),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (title.isNotEmpty()) Text(title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
            if (subtitle.isNotEmpty()) Muted(subtitle)
            content()
        }
    }
}

@Composable
fun Muted(text: String, modifier: Modifier = Modifier) = Text(text, modifier, color = Palette.muted, fontSize = 14.sp)

@Composable
fun Mono(text: String, modifier: Modifier = Modifier, maxLines: Int = Int.MAX_VALUE) =
    Text(text, modifier, fontFamily = FontFamily.Monospace, fontSize = 13.sp, maxLines = maxLines, overflow = TextOverflow.Ellipsis)

enum class Badge(val fg: Color, val bg: Color) {
    NEUTRAL(Palette.muted, Color(0xFF2A2E38)),
    INFO(Palette.info, Color(0xFF1B2840)),
    SUCCESS(Palette.success, Color(0xFF173226)),
    WARNING(Palette.warning, Color(0xFF3A3017)),
    ERROR(Palette.error, Color(0xFF3D1D1B)),
}

@Composable
fun StatusBadge(text: String, kind: Badge, modifier: Modifier = Modifier) {
    if (text.isEmpty()) return
    Text(
        text,
        modifier.fillMaxWidth().background(kind.bg, RoundedCornerShape(8.dp))
            .border(1.dp, kind.fg.copy(alpha = 0.35f), RoundedCornerShape(8.dp)).padding(10.dp),
        color = kind.fg, fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
    )
}

@Composable
fun IssueText(issues: List<Issue>, vararg fields: String) {
    val match = issues.filter { it.field in fields }.sortedBy { it.level != ERROR }
    for (i in match) Text(
        (if (i.level == ERROR) "✖ " else "⚠ ") + i.message,
        color = if (i.level == ERROR) Palette.error else Palette.warning, fontSize = 13.sp,
    )
}

@Composable
fun PrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) =
    Button(onClick, modifier.testTag(text), enabled = enabled,
        colors = ButtonDefaults.buttonColors(containerColor = Palette.accent, contentColor = Palette.accentText)) { Text(text) }

@Composable
fun SecondaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) =
    OutlinedButton(onClick, modifier.testTag(text), enabled = enabled) { Text(text) }

/** A button that briefly shows "Copied ✓" after a click. */
@Composable
fun CopyButton(label: String = "Copy", tag: String = label, onCopy: () -> Unit) {
    var copied by remember { mutableStateOf(false) }
    LaunchedEffect(copied) { if (copied) { delay(1400); copied = false } }
    TextButton({ onCopy(); copied = true }, Modifier.testTag(tag)) { Text(if (copied) "Copied ✓" else label) }
}

/** A labelled value with a copy action (non-secret values such as names and fingerprints). */
@Composable
fun CopyRow(label: String, value: String, onCopy: () -> Unit, tag: String = "copy_$label") {
    Column {
        if (label.isNotEmpty()) Muted(label)
        Row(verticalAlignment = Alignment.CenterVertically) {
            SelectionContainer(Modifier.weight(1f)) { Mono(value) }
            CopyButton(tag = tag, onCopy = onCopy)
        }
    }
}

/** A masked secret. The value is only fetched from [provider] when the user taps Show or Copy. */
@Composable
fun SecretRow(label: String, provider: (() -> String)?, onCopy: (String) -> Unit, onError: (Throwable) -> Unit, tag: String = label) {
    var shown by remember(provider) { mutableStateOf<String?>(null) }
    Column(Modifier.testTag("secret_$tag")) {
        Muted(label)
        Row(verticalAlignment = Alignment.CenterVertically) {
            val display = shown?.let { if (it.length > 120) it.take(120) + "…" else it } ?: "••••••••••••"
            Mono(display, Modifier.weight(1f), maxLines = 3)
            TextButton({
                if (shown != null) shown = null
                else runCatching { provider!!() }.onSuccess { shown = it }.onFailure(onError)
            }, enabled = provider != null) { Text(if (shown == null) "Show" else "Hide") }
            CopyButton("Copy", "copy_secret_$tag") {
                runCatching { provider!!() }.onSuccess(onCopy).onFailure(onError)
            }
        }
    }
}
