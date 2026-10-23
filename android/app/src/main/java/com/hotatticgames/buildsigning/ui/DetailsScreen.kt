package com.hotatticgames.buildsigning.ui

import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.hotatticgames.buildsigning.AppState
import com.hotatticgames.buildsigning.core.CHANNELS
import com.hotatticgames.buildsigning.core.Issue
import com.hotatticgames.buildsigning.core.Profile
import com.hotatticgames.buildsigning.core.inspectIcon

@Composable
fun Field(label: String, value: String, issues: List<Issue>, field: String, tag: String = field, placeholder: String = "",
          keyboard: KeyboardType = KeyboardType.Text, onChange: (String) -> Unit) {
    val mine = issues.filter { it.field == field }
    Column {
        OutlinedTextField(
            value, onChange, Modifier.fillMaxWidth().testTag("field_$tag"),
            label = { Text(label) }, singleLine = true, isError = mine.any { it.level == "error" },
            placeholder = { if (placeholder.isNotEmpty()) Text(placeholder) },
            keyboardOptions = KeyboardOptions(keyboardType = keyboard),
        )
        IssueText(issues, field)
    }
}

@Composable
fun DetailsScreen(state: AppState) {
    state.revision
    val p: Profile = state.profile ?: return
    val issues = remember(state.revision, state.identitiesRevision) { state.issues(p) }
    val plats = p.enabledPlatforms()
    // The build number field keeps its own text so partial input (e.g. empty) can be typed.
    var buildText by remember(p.id) { mutableStateOf(p.buildNumber.toString()) }

    val iconPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            runCatching {
                state.context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            state.edit { it.iconPath = uri.toString() }
        }
    }

    ScreenColumn("Application Details", "Basic information about the application. Identifiers are only required for the platforms you select.") {
        Section("General") {
            Field("Application name", p.name, issues, "name") { v -> state.edit { it.name = v } }
            Field("Publisher", p.publisher, issues, "publisher") { v -> state.edit { it.publisher = v } }
            Field("Version", p.version, issues, "version", placeholder = "e.g. 1.0.0") { v -> state.edit { it.version = v.trim() } }
            Column {
                OutlinedTextField(buildText, { v ->
                    buildText = v.filter { it.isDigit() }.take(10)
                    state.edit { it.buildNumber = buildText.toLongOrNull() ?: 0 }
                }, Modifier.fillMaxWidth().testTag("field_build_number"), label = { Text("Build number") }, singleLine = true,
                    isError = issues.any { it.field == "build_number" },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                IssueText(issues, "build_number")
                Muted("Must increase with every release (Android versionCode, Apple CFBundleVersion).")
            }
            Muted("Release channel")
            for ((key, label) in CHANNELS) {
                Row(Modifier.fillMaxWidth().selectable(p.releaseChannel == key) { state.edit { it.releaseChannel = key } }
                    .testTag("channel_$key"), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(p.releaseChannel == key, { state.edit { it.releaseChannel = key } })
                    Text(label)
                }
            }
        }

        Section("Application identifiers", "Identifiers must never change after release, otherwise stores and devices treat the build as a different app.") {
            var any = false
            if ("android" in plats) { any = true
                Field("Android package name", p.androidPackage, issues, "android_package", placeholder = "com.hotatticgames.mygame") { v -> state.edit { it.androidPackage = v.trim() } } }
            if ("ios" in plats || "macos" in plats) { any = true
                Field("Apple bundle identifier", p.appleBundleId, issues, "apple_bundle_id", placeholder = "com.hotatticgames.mygame") { v -> state.edit { it.appleBundleId = v.trim() } } }
            if ("macos" in plats) { any = true
                Field("macOS bundle identifier", p.macosBundleId, issues, "macos_bundle_id", placeholder = "Blank = same as Apple bundle identifier") { v -> state.edit { it.macosBundleId = v.trim() } } }
            if ("windows" in plats || "linux" in plats) { any = true
                Field("Desktop identifier (optional)", p.desktopAppId, issues, "desktop_app_id", placeholder = "com.hotatticgames.mygame") { v -> state.edit { it.desktopAppId = v.trim() } } }
            if (!any) Muted("Select platforms on the Platforms & Stores screen to see the identifiers they need.")
        }

        Section("Application icon", "Reference to an existing icon file. The file is not copied or modified, and no artwork is generated.") {
            if (p.iconPath.isEmpty()) Muted("No icon selected") else {
                Mono(state.documents.displayName(android.net.Uri.parse(p.iconPath)))
                val info = remember(p.iconPath) { inspectIcon(p.iconPath, state.documents.iconReader) }
                if (info.exists && info.error.isEmpty())
                    Muted("Detected: ${info.kind.uppercase()}" + if (info.width > 0) ", ${info.width}×${info.height}" else "")
            }
            IssueText(issues, "icon_path")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SecondaryButton("Choose Icon", { iconPicker.launch(arrayOf("image/*")) })
                if (p.iconPath.isNotEmpty()) SecondaryButton("Clear", { state.edit { it.iconPath = "" } })
            }
            Muted("Recommended: a square PNG of at least 1024×1024 (Apple), 512×512 (Google Play); Windows executables use .ico.")
        }
    }
}
