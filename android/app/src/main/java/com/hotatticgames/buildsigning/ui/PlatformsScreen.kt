package com.hotatticgames.buildsigning.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.hotatticgames.buildsigning.AppState
import com.hotatticgames.buildsigning.core.GUIDANCE
import com.hotatticgames.buildsigning.core.PLATFORMS
import com.hotatticgames.buildsigning.core.STORES

@Composable
fun CheckRow(label: String, checked: Boolean, tag: String, enabled: Boolean = true, bold: Boolean = false, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().toggleable(checked, enabled) { onChange(it) }.testTag(tag), verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked, null, enabled = enabled)
        Text(label, fontWeight = if (bold) FontWeight.SemiBold else null, color = if (enabled) Palette.text else Palette.muted)
    }
}

@Composable
fun PlatformsScreen(state: AppState) {
    state.revision
    val p = state.profile ?: return
    val issues = remember(state.revision) { state.issues(p) }

    ScreenColumn("Platforms & Stores", "Choose what this project should be built for. Selecting a platform records what you want; " +
        "the generated prompt asks the development agent to check what the project can actually build.") {
        for (spec in PLATFORMS) {
            val choice = p.platforms.getValue(spec.key)
            Section {
                CheckRow(spec.label, choice.enabled, "platform_${spec.key}", bold = true) { on -> state.edit { it.platforms.getValue(spec.key).enabled = on } }
                Column(Modifier.padding(start = 24.dp)) {
                    for ((fkey, flabel) in spec.formats) {
                        CheckRow(flabel, fkey in choice.formats, "format_${spec.key}_$fkey", enabled = choice.enabled) { on ->
                            state.edit {
                                val fs = it.platforms.getValue(spec.key).formats
                                if (on && fkey !in fs) fs.add(fkey) else if (!on) fs.remove(fkey)
                            }
                        }
                    }
                }
                IssueText(issues, "formats.${spec.key}")
                Muted(GUIDANCE.getValue(spec.key).substringBefore(". ") + ".")
            }
        }
        IssueText(issues, "platforms")
        Section("Target stores", "Used only to tailor the generated instructions. Nothing is submitted or published.") {
            for ((key, label) in STORES) {
                CheckRow(label, key in p.stores, "store_$key") { on ->
                    state.edit { if (on && key !in it.stores) it.stores.add(key) else if (!on) it.stores.remove(key) }
                }
            }
            IssueText(issues, "stores")
        }
    }
}
