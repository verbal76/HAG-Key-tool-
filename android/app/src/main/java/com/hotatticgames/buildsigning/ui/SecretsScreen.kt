package com.hotatticgames.buildsigning.ui

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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import com.hotatticgames.buildsigning.AppState
import com.hotatticgames.buildsigning.Level
import com.hotatticgames.buildsigning.core.SecretNames

private const val INSTRUCTIONS = """How to add these secrets to GitHub:
1. Open the repository on github.com and go to Settings → Secrets and variables → Actions.
2. Tap “New repository secret”.
3. Paste the secret name into “Name”, and the matching value into “Secret”.
4. Tap “Add secret”. Repeat for all four.
GitHub never shows a secret value again after it is saved. If a name already exists, choose “Yes, add a numeric suffix” above instead of overwriting it."""

@Composable
fun SecretsScreen(state: AppState) {
    state.revision
    state.identitiesRevision
    val p = state.profile ?: return
    var suffixText by remember(p.id) { mutableStateOf(p.secretSuffix.toString()) }
    val suffixError = if (p.secretUseSuffix) SecretNames.validateSuffix(suffixText) else ""
    val names = runCatching { SecretNames.forProfile(p) }.getOrNull()
    val rec = state.identity()

    ScreenColumn("GitHub Secrets", "GitHub Actions reads the Android signing credentials from repository secrets. " +
        "Check the names below against your repository before adding values.") {
        if (!p.isEnabled("android")) StatusBadge("Android is not selected for this project, so no Android signing secrets are needed.", Badge.INFO)

        Section("1. Secret names", "A secret name is only a label in your repository. Changing it never changes or regenerates your signing key.") {
            Text("Have you already used these secret names in this repository?", fontWeight = FontWeight.SemiBold)
            Muted("Default names: " + SecretNames.DEFAULT_NAMES.values.joinToString(", "))
            for ((use, label) in listOf(false to "No, use the default names", true to "Yes, add a numeric suffix")) {
                Row(Modifier.fillMaxWidth().selectable(p.secretUseSuffix == use) { state.edit { it.secretUseSuffix = use } }
                    .testTag("suffix_$use"), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(p.secretUseSuffix == use, { state.edit { it.secretUseSuffix = use } })
                    Text(label)
                }
            }
            if (p.secretUseSuffix) {
                OutlinedTextField(suffixText, { v ->
                    suffixText = v.filter { it.isDigit() }.take(4)
                    suffixText.toLongOrNull()?.let { n -> state.edit { it.secretSuffix = n } }
                }, Modifier.fillMaxWidth().testTag("suffix_value"), label = { Text("Suffix") }, singleLine = true,
                    isError = suffixError.isNotEmpty(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    supportingText = { if (suffixError.isNotEmpty()) Text(suffixError) })
            }
            Muted("This app has not checked your repository. Look under Settings → Secrets and variables → Actions to see which names already exist.")
            Text("Final secret names", fontWeight = FontWeight.SemiBold)
            if (names != null && suffixError.isEmpty()) {
                for ((role, name) in names) CopyRow(SecretNames.ROLE_DESCRIPTIONS.getValue(role), name,
                    { state.clipboard.copy("Secret name", name) }, "copy_name_$role")
                CopyButton("Copy All Names", "copy_all_names") { state.clipboard.copy("Secret names", names.values.joinToString("\n")) }
            } else StatusBadge(suffixError.ifEmpty { "Enter a valid suffix." }, Badge.ERROR)
        }

        Section("2. Secret values", "Values are masked. They are copied only when you tap Copy, and are never included in the generated " +
            "prompt or exported profiles.") {
            if (rec == null || names == null) {
                StatusBadge("Generate or import an Android signing identity on the Signing Identities screen to see the values.", Badge.NEUTRAL)
            } else {
                val id = rec.id
                val vault = state.vault
                val providers = linkedMapOf<String, () -> String>(
                    "keystore_base64" to { vault.keystoreBase64(id) },
                    "keystore_password" to { vault.credentials(id).storePassword },
                    "key_alias" to { rec.alias },
                    "key_password" to { vault.credentials(id).keyPassword },
                )
                Column {
                    for ((role, provider) in providers) SecretRow(names.getValue(role), provider,
                        { state.clipboard.copy(names.getValue(role), it, sensitive = true) },
                        { state.say("Credentials could not be read: ${it.message}", Level.ERROR) }, tag = role)
                }
            }
        }

        Section("3. Add them to GitHub") { Muted(INSTRUCTIONS) }
    }
}
