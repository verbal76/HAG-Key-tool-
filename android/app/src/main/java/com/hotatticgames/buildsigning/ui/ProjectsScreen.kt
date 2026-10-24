package com.hotatticgames.buildsigning.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.hotatticgames.buildsigning.AppState
import com.hotatticgames.buildsigning.Level
import com.hotatticgames.buildsigning.core.CHANNEL_LABELS
import com.hotatticgames.buildsigning.core.PLATFORM_BY_KEY
import com.hotatticgames.buildsigning.core.Profile

fun signingSummary(state: AppState, p: Profile): String = when {
    p.androidIdentityId.isEmpty() -> if (p.isEnabled("android")) "Signing: not configured" else "Signing: not required"
    !state.vault.exists(p.androidIdentityId) -> "Signing: identity missing!"
    state.vault.get(p.androidIdentityId).hasVerifiedBackup -> "Signing: backed up"
    else -> "Signing: not backed up"
}

private sealed interface ProjectDialog {
    data object New : ProjectDialog
    data class Rename(val p: Profile) : ProjectDialog
    data class Delete(val p: Profile) : ProjectDialog
    data class ImportConflict(val p: Profile) : ProjectDialog
}

@Composable
fun ProjectsScreen(state: AppState, guard: UnsavedGuard, onOpened: () -> Unit) {
    var dialog by remember { mutableStateOf<ProjectDialog?>(null) }
    var exporting by remember { mutableStateOf<Profile?>(null) }

    val exportLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        val p = exporting ?: return@rememberLauncherForActivityResult
        exporting = null
        if (uri != null) runCatching { state.documents.writeNew(uri, state.exportBytes(p)) }
            .onSuccess { state.say("Exported profile. It contains no passwords or keys.", Level.SUCCESS) }
            .onFailure { state.say(it.message ?: "Export failed.", Level.ERROR) }
    }
    val importLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) state.readImport(uri)?.let { (p, conflict) ->
            if (conflict) dialog = ProjectDialog.ImportConflict(p) else state.importProfile(p, "new")
        }
    }

    ScreenColumn("Projects", "Create, open and manage the build profile for each of your applications.") {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PrimaryButton("New Project", { dialog = ProjectDialog.New })
            SecondaryButton("Import Profile", { importLauncher.launch(arrayOf("application/json", "text/plain", "*/*")) })
        }
        if (state.profiles.isEmpty()) Muted("No projects yet. Tap New Project to create your first profile.")
        for (p in state.profiles) {
            val isOpen = state.profile?.id == p.id
            val shown = if (isOpen) state.profile!! else p
            ProjectCard(state, shown, isOpen,
                onOpen = { if (isOpen) onOpened() else guard.run(state) { state.openById(p.id); onOpened() } },
                onDuplicate = { state.duplicate(p) },
                onRename = { dialog = ProjectDialog.Rename(shown) },
                onDelete = { dialog = ProjectDialog.Delete(p) },
                onExport = { exporting = shown; exportLauncher.launch("${shown.slug()}-profile.json") },
            )
        }
        if (state.broken.isNotEmpty()) Section("Profiles that could not be read", "These files were left untouched.") {
            for (b in state.broken) Muted("${b.file.name}: ${b.error}")
        }
    }

    when (val d = dialog) {
        null -> {}
        ProjectDialog.New -> TextInputDialog("New Project", "Application name", "", "Create", { dialog = null }) {
            dialog = null
            guard.run(state) { state.newProject(it); onOpened() }
        }
        is ProjectDialog.Rename -> TextInputDialog("Rename Project", "Application name", d.p.name, "Rename", { dialog = null }) {
            dialog = null
            if (it.isNotBlank()) state.rename(d.p, it)
        }
        is ProjectDialog.Delete -> {
            val rec = state.identityFor(d.p)
            AlertDialog(
                onDismissRequest = { dialog = null },
                title = { Text("Delete project") },
                text = {
                    Text("Delete the project profile “${d.p.name.ifEmpty { "Untitled" }}”?\n\n" +
                        (rec?.let { "This project uses the Android signing identity “${it.label}”. The identity and its " +
                            "backups will NOT be deleted; they stay in the vault and can be linked to another project.\n\n" } ?: "") +
                        "The profile file is moved to a 'deleted' folder inside the app's data so it can be recovered.")
                },
                confirmButton = { TextButton({ dialog = null; state.delete(d.p) }, Modifier.testTag("confirm_delete")) { Text("Delete") } },
                dismissButton = { TextButton({ dialog = null }) { Text("Cancel") } },
            )
        }
        is ProjectDialog.ImportConflict -> AlertDialog(
            onDismissRequest = { dialog = null },
            title = { Text("Project already exists") },
            text = { Text("A project with the same internal id (“${d.p.name}”) already exists. Import as a copy, or replace " +
                "the saved project? Replacing does not affect signing identities.") },
            confirmButton = { TextButton({ dialog = null; state.importProfile(d.p, "copy") }) { Text("Import as Copy") } },
            dismissButton = { TextButton({ dialog = null; state.importProfile(d.p, "replace") }) { Text("Replace Existing") } },
        )
    }
}

@Composable
private fun ProjectCard(state: AppState, p: Profile, isOpen: Boolean, onOpen: () -> Unit, onDuplicate: () -> Unit,
                        onRename: () -> Unit, onDelete: () -> Unit, onExport: () -> Unit) {
    var menu by remember { mutableStateOf(false) }
    Section(modifier = Modifier.clickable(onClick = onOpen).testTag("project_${p.name}")) {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Text(p.name.ifEmpty { "Untitled" } + if (isOpen) "  (open)" else "", fontWeight = FontWeight.SemiBold)
                Muted(p.publisher)
                Muted(p.enabledPlatforms().joinToString(", ") { PLATFORM_BY_KEY.getValue(it).label }.ifEmpty { "No platforms selected" })
                Muted("v${p.version} · build ${p.buildNumber} · ${CHANNEL_LABELS[p.releaseChannel]}")
                Muted("Modified ${p.modifiedAt.replace('T', ' ').take(16)} UTC · ${signingSummary(state, p)}")
            }
            Box {
                IconButton({ menu = true }, Modifier.testTag("menu_${p.name}")) { Icon(Icons.Filled.MoreVert, "Actions") }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem({ Text("Open") }, { menu = false; onOpen() })
                    DropdownMenuItem({ Text("Duplicate") }, { menu = false; onDuplicate() })
                    DropdownMenuItem({ Text("Rename") }, { menu = false; onRename() })
                    DropdownMenuItem({ Text("Export Profile") }, { menu = false; onExport() })
                    DropdownMenuItem({ Text("Delete") }, { menu = false; onDelete() }, Modifier.testTag("delete_${p.name}"))
                }
            }
        }
    }
}

@Composable
fun TextInputDialog(title: String, label: String, initial: String, confirm: String, onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var text by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth().testTag("dialog_input"),
                label = { Text(label) }, singleLine = true)
        },
        confirmButton = { TextButton({ onConfirm(text) }, Modifier.testTag("dialog_confirm")) { Text(confirm) } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } },
    )
}
