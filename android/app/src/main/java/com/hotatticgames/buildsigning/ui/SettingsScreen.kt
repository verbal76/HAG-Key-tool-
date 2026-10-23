package com.hotatticgames.buildsigning.ui

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.hotatticgames.buildsigning.AppState
import com.hotatticgames.buildsigning.core.APP_NAME
import com.hotatticgames.buildsigning.core.APP_VERSION

@Composable
fun SettingsScreen(state: AppState) {
    state.revision
    ScreenColumn("Settings", "Clipboard behaviour, storage and signing engines.") {
        Section("Clipboard", "Copied passwords and keys are marked sensitive, so Android hides them in its clipboard preview. " +
            "They are cleared after the delay below — only if the clipboard still holds that value.") {
            for ((secs, label) in listOf(30 to "30 seconds", 60 to "60 seconds", 120 to "2 minutes", 0 to "Never clear")) {
                Row(Modifier.fillMaxWidth().selectable(state.clipboardClearSeconds == secs) { state.clipboardClearSeconds = secs },
                    verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(state.clipboardClearSeconds == secs, { state.clipboardClearSeconds = secs })
                    Text(label)
                }
            }
        }
        Section("Signing engines") {
            Muted("Key generation and keystores: BouncyCastle (RSA 4096, PKCS12 with AES-256). Existing JKS and PKCS12 keystores can be imported.")
            Muted("APK verification: apksig, Google's library behind the apksigner tool (APK Signature Schemes v1–v4).")
            Muted("No external tools or network access are needed.")
        }
        Section("Storage") {
            Muted("Projects: ${state.store.dir}")
            Muted("Signing identity vault: ${state.vault.dir}")
            Muted("Stored passwords are protected with: ${state.vault.protector.schemeName}.")
            Muted("App data is excluded from Android cloud backup and device transfer. Use encrypted backups (.hagbackup) to move " +
                "identities between devices — they work in both the Android and the Windows app.")
            Muted("Deleted project profiles are kept in the 'profiles/deleted' folder.")
        }
        Section("About") {
            Muted("$APP_NAME $APP_VERSION (Android)\nPrivate test build — not for public distribution.")
        }
    }
}
