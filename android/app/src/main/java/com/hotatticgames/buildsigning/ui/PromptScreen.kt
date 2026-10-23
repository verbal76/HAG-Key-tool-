package com.hotatticgames.buildsigning.ui

import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.hotatticgames.buildsigning.AppState
import com.hotatticgames.buildsigning.Level
import com.hotatticgames.buildsigning.core.ERROR
import com.hotatticgames.buildsigning.core.PromptGenerator

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PromptScreen(state: AppState) {
    state.revision
    state.identitiesRevision
    val p = state.profile ?: return
    val issues = remember(state.revision, state.identitiesRevision) { state.issues(p) }
    val errors = issues.filter { it.level == ERROR }
    val warnings = issues.filter { it.level != ERROR }
    val prompt = if (errors.isEmpty()) PromptGenerator.generate(p, state.identity()?.fingerprintSha256 ?: "") else ""

    val saver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/plain")) { uri ->
        if (uri != null) runCatching { state.documents.writeNew(uri, prompt.toByteArray()) }
            .onSuccess { state.say("Prompt saved.", Level.SUCCESS) }
            .onFailure { state.say(it.message ?: "Save failed.", Level.ERROR) }
    }

    ScreenColumn("Generated Prompt", "A complete, engine-independent instruction for a Claude development session that configures the " +
        "build workflow of the selected project. It never contains passwords or keys.") {
        when {
            errors.isNotEmpty() -> StatusBadge("Fix these before generating the prompt:\n" + errors.joinToString("\n") { "• ${it.message}" }, Badge.ERROR,
                Modifier.testTag("prompt_errors"))
            warnings.isNotEmpty() -> StatusBadge("Generated with warnings:\n" + warnings.joinToString("\n") { "• ${it.message}" }, Badge.WARNING)
            else -> StatusBadge("Prompt is up to date with the project settings.", Badge.INFO)
        }
        if (prompt.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimaryButton("Copy Prompt", { state.clipboard.copy("Build prompt", prompt); state.say("Prompt copied.", Level.SUCCESS) })
                SecondaryButton("Save as Text", { saver.launch("${p.slug()}-build-prompt.txt") })
                SecondaryButton("Share", {
                    val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, prompt)
                    state.context.startActivity(Intent.createChooser(send, "Share prompt").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                })
            }
            Section {
                SelectionContainer { Mono(prompt, Modifier.testTag("prompt_text")) }
            }
            Muted("Paste this prompt into a Claude Code session opened on the game's repository. It updates automatically when you change project settings.")
        }
    }
}
