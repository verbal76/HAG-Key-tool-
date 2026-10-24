package com.hotatticgames.buildsigning.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.hotatticgames.buildsigning.AppState
import com.hotatticgames.buildsigning.Level
import com.hotatticgames.buildsigning.core.AliasEntry
import com.hotatticgames.buildsigning.core.AndroidSigning
import com.hotatticgames.buildsigning.core.Backup
import com.hotatticgames.buildsigning.core.CMP_MATCH
import com.hotatticgames.buildsigning.core.CMP_MISMATCH
import com.hotatticgames.buildsigning.core.DName
import com.hotatticgames.buildsigning.core.GUIDANCE
import com.hotatticgames.buildsigning.core.IdentityRecord
import com.hotatticgames.buildsigning.core.KEY_SIZE
import com.hotatticgames.buildsigning.core.PLATFORM_BY_KEY
import com.hotatticgames.buildsigning.core.SIGNATURE_ALGORITHM
import com.hotatticgames.buildsigning.core.generatePassword
import com.hotatticgames.buildsigning.core.proposedNames
import com.hotatticgames.buildsigning.core.slugify

fun identityStatus(state: AppState, rec: IdentityRecord?): Pair<String, Badge> {
    if (rec == null) {
        if (state.profile?.androidIdentityId?.isNotEmpty() == true)
            return "The linked signing identity is missing from this device's vault. Restore it from a backup." to Badge.ERROR
        return "No signing identity configured." to Badge.NEUTRAL
    }
    val base = when (rec.source) {
        "generated" -> "Signing identity generated"
        "restored" -> "Signing identity restored from backup"
        else -> "Existing signing identity imported"
    }
    return when {
        rec.hasVerifiedBackup -> "$base and backed up (recovery verified)." to Badge.SUCCESS
        rec.hasAnyBackup -> "$base; backup created but its recovery has not been verified." to Badge.WARNING
        else -> "$base but not backed up." to Badge.WARNING
    }
}

private sealed interface SigningDialog {
    data object Generate : SigningDialog
    data class Import(val bytes: ByteArray, val name: String) : SigningDialog
    data object Link : SigningDialog
    data object Backup : SigningDialog
    data class Passphrase(val purpose: String, val uri: Uri) : SigningDialog   // "test" or "restore"
    data object ExportKeystore : SigningDialog
    data class Info(val title: String, val text: String, val tag: String = "info_dialog") : SigningDialog
    data object BackUpNow : SigningDialog
    data class LinkRestored(val rec: IdentityRecord, val created: Boolean) : SigningDialog
    data class ConfirmReplace(val id: String) : SigningDialog
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SigningScreen(state: AppState) {
    state.revision
    state.identitiesRevision
    val p = state.profile ?: return
    val rec = state.identity()
    var dialog by remember { mutableStateOf<SigningDialog?>(null) }
    var pendingPassphrase by remember { mutableStateOf("") }
    val busy = state.busy != null

    fun link(id: String) {
        val current = p.androidIdentityId
        if (current.isNotEmpty() && current != id && state.vault.exists(current)) dialog = SigningDialog.ConfirmReplace(id)
        else state.linkIdentity(id)
    }

    val importPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) runCatching { state.documents.read(uri) to state.documents.displayName(uri) }
            .onSuccess { (b, n) -> dialog = SigningDialog.Import(b, n) }
            .onFailure { state.say(it.message ?: "The file could not be read.", Level.ERROR) }
    }
    val backupCreator = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        val r = rec
        val pass = pendingPassphrase
        pendingPassphrase = ""
        if (uri == null || r == null) return@rememberLauncherForActivityResult
        val name = state.documents.displayName(uri)
        state.run("Creating and verifying encrypted backup…", {
            val data = Backup.create(state.vault, r.id, pass, state.backupScryptN())
            val readBack = state.documents.writeNew(uri, data)
            if (!readBack.contentEquals(data)) Backup.VerifyResult(false, "The saved file does not match what was written. Try another location.")
            else Backup.verify(readBack, pass, r.fingerprintSha256)
        }) { result ->
            state.recordBackup(r.id, name, result.ok)
            dialog = if (result.ok) SigningDialog.Info("Backup verified", "Saved as $name.\n\n${result.message}\n\n" +
                "Keep the passphrase somewhere safe and separate from the file.", "backup_ok")
            else SigningDialog.Info("Backup not verified", "The file $name was written but could not be verified:\n" +
                "${result.message}\n\nDo not rely on it until a recovery test passes.")
        }
    }
    val backupOpener = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        val purpose = pendingPassphrase
        pendingPassphrase = ""
        if (uri != null) dialog = SigningDialog.Passphrase(purpose, uri)
    }
    val keystoreExporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        val r = rec ?: return@rememberLauncherForActivityResult
        if (uri != null) runCatching { state.documents.writeNew(uri, state.vault.keystoreBytes(r.id)) }
            .onSuccess { state.say("Keystore file exported. Keep it private.", Level.WARNING) }
            .onFailure { state.say(it.message ?: "Export failed.", Level.ERROR) }
    }
    val apkPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> if (uri != null) state.inspectApk(uri) }

    ScreenColumn("Signing Identities", "Create, import, inspect and back up the credentials that sign your releases. " +
        "Android signing is fully managed here; other platforms show what they require.") {
        Section("Android signing identity") {
            if (!p.isEnabled("android")) Muted("Android is not selected for this project, so Android signing is optional.")
            val (text, badge) = identityStatus(state, rec)
            StatusBadge(text, badge, Modifier.testTag("signing_status"))
            state.lastApk?.let { r ->
                val kind = when (r.comparison.result) { CMP_MATCH -> Badge.SUCCESS; else -> Badge.ERROR }
                val label = when (r.comparison.result) {
                    CMP_MATCH -> "Certificate matches selected APK (${r.name})."
                    CMP_MISMATCH -> "Certificate mismatch detected (${r.name})."
                    else -> "${r.comparison.title} (${r.name})."
                }
                StatusBadge(label, kind, Modifier.testTag("apk_status"))
            }
            if (rec != null) {
                Muted("Identity"); Text(rec.label)
                Muted("Keystore"); Mono("${rec.keystoreFilename} (${rec.storeType}, stored in the app's private vault)")
                CopyRow("Key alias", rec.alias, { state.clipboard.copy("Key alias", rec.alias) })
                CopyRow("Certificate SHA-256", rec.fingerprintSha256, { state.clipboard.copy("SHA-256", rec.fingerprintSha256) }, "copy_sha256")
                Muted("Certificate SHA-1"); Mono(rec.fingerprintSha1)
                Muted("Valid"); Text("${rec.notBefore.take(10)} to ${rec.notAfter.take(10)} · ${rec.keyAlgorithm} ${rec.keySize}-bit")
                Muted("Subject"); Text(rec.subject)
                val id = rec.id
                SecretRow("Keystore password", { state.vault.credentials(id).storePassword },
                    { state.clipboard.copy("Keystore password", it, sensitive = true) }, { state.say("Credentials unavailable: ${it.message}", Level.ERROR) },
                    tag = "store_password")
                SecretRow("Key password", { state.vault.credentials(id).keyPassword },
                    { state.clipboard.copy("Key password", it, sensitive = true) }, { state.say("Credentials unavailable: ${it.message}", Level.ERROR) },
                    tag = "key_password")
                Muted(when {
                    rec.storeType == "PKCS12" -> "PKCS12 keystores use one password for the keystore and the key, so both values are identical."
                    rec.keyPasswordMatchesStore -> "The key password is the same as the keystore password."
                    else -> "This keystore uses a separate key password."
                })
                Muted("Backups")
                if (rec.backups.isEmpty()) Text("No backups yet. Create one now.", color = Palette.warning)
                for (b in rec.backups) Text("${if (b.verified) "✔ verified" else "✖ not verified"} — ${b.path} (${b.createdAt.take(10)})", color = if (b.verified) Palette.success else Palette.warning)
                StatusBadge("These credentials are essential for every future release. Never share them, commit them to Git or paste them into chats.", Badge.WARNING)
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (rec == null) PrimaryButton("Generate New Android Signing Identity", { dialog = SigningDialog.Generate }, enabled = !busy)
                else SecondaryButton("Generate New Android Signing Identity", { dialog = SigningDialog.Generate }, enabled = !busy)
                SecondaryButton("Import Existing Keystore", { importPicker.launch(arrayOf("*/*")) }, enabled = !busy)
                SecondaryButton("Use Identity From Vault", { dialog = SigningDialog.Link }, enabled = !busy && state.vault.list().isNotEmpty())
                SecondaryButton("Back Up Signing Identity", { dialog = SigningDialog.Backup }, enabled = !busy && rec != null)
                SecondaryButton("Test Backup Recovery", { pendingPassphrase = "test"; backupOpener.launch(arrayOf("*/*")) }, enabled = !busy && rec != null)
                SecondaryButton("Restore From Backup", { pendingPassphrase = "restore"; backupOpener.launch(arrayOf("*/*")) }, enabled = !busy)
                SecondaryButton("Inspect APK Certificate", { apkPicker.launch(arrayOf("application/vnd.android.package-archive", "*/*")) }, enabled = !busy)
                SecondaryButton("Export Keystore File", { dialog = SigningDialog.ExportKeystore }, enabled = !busy && rec != null)
            }
        }

        state.lastApk?.let { r ->
            Section("Last APK inspection") {
                Muted("File: ${r.name}")
                Text("Result: ${r.comparison.title}")
                Muted("Inspection: ${r.inspection.message}")
                if (r.inspection.signerSha256.isNotEmpty()) { Muted("APK signer SHA-256:"); r.inspection.signerSha256.forEach { Mono(it) } }
                if (r.inspection.schemes.isNotEmpty()) Muted("Signature schemes: " + r.inspection.schemes.entries.joinToString(", ") {
                    "${it.key} ${when (it.value) { true -> "yes"; false -> "no"; null -> "unknown" }}" })
                r.comparison.notes.forEach { Muted("• $it") }
            }
        }

        val others = p.enabledPlatforms().filter { it != "android" }
        if (others.isNotEmpty()) Section("Other platforms", "An Android keystore cannot sign Windows, Apple, Linux or web builds. " +
            "These platforms use their own credentials, which this version does not create.") {
            for (k in others) Muted("${PLATFORM_BY_KEY.getValue(k).label}: ${GUIDANCE.getValue(k)}")
        }
    }

    when (val d = dialog) {
        null -> {}
        SigningDialog.Generate -> GenerateDialog(state, rec, { dialog = null }) { v ->
            dialog = null
            state.run("Generating signing identity (RSA $KEY_SIZE-bit)…", {
                state.vault.generate(p.name.ifEmpty { "Untitled" }, v.alias, v.filename, v.dname, v.validityDays)
            }) { r ->
                state.linkIdentity(r.id)
                state.identitiesChanged()
                state.say("Signing identity generated and verified. Back it up now.", Level.WARNING)
                dialog = SigningDialog.BackUpNow
            }
        }
        is SigningDialog.Import -> ImportDialog(state, d.bytes, d.name, { dialog = null }) { storePw, alias, keyPw ->
            dialog = null
            state.run("Importing keystore…", {
                val cert = AndroidSigning.readCertificate(d.bytes, storePw, alias)
                val existing = state.vault.findByFingerprint(cert.sha256).firstOrNull()
                if (existing != null) existing to false
                else state.vault.importKeystore(d.bytes, d.name, storePw, alias, keyPw, p.name) to true
            }) { (r, created) ->
                state.identitiesChanged()
                link(r.id)
                state.say(if (created) "Keystore imported and verified. Back it up if you have no other copy."
                    else "This key was already in the vault as “${r.label}”; that identity is now linked.", Level.INFO)
            }
        }
        SigningDialog.Link -> LinkDialog(state.vault.list(), p.androidIdentityId, { dialog = null }) { id -> dialog = null; link(id) }
        SigningDialog.Backup -> BackupPassphraseDialog(state, { dialog = null }) { pass ->
            dialog = null
            pendingPassphrase = pass
            val base = slugify(rec?.label ?: "signing", "-").ifEmpty { "signing" }
            backupCreator.launch("$base-identity${Backup.EXTENSION}")
        }
        is SigningDialog.Passphrase -> PassphraseDialog(
            if (d.purpose == "test") "Test Backup Recovery" else "Restore From Backup",
            if (d.purpose == "test") "Decrypts the backup, opens the keystore inside it with the stored passwords and checks the certificate " +
                "matches this identity. Nothing is changed."
            else "Restores a signing identity into this device's vault from an encrypted backup. Existing identities are never replaced.",
            { dialog = null },
        ) { pass ->
            dialog = null
            val name = state.documents.displayName(d.uri)
            if (d.purpose == "test") {
                val r = rec ?: return@PassphraseDialog
                state.run("Testing backup recovery…", { Backup.verify(state.documents.read(d.uri), pass, r.fingerprintSha256) }) { result ->
                    state.vault.recordRecoveryTest(r.id, name, result.ok, result.message)
                    state.identitiesChanged()
                    dialog = SigningDialog.Info(if (result.ok) "Recovery test passed" else "Recovery test failed", result.message, "recovery_result")
                }
            } else {
                state.run("Restoring from backup…", { Backup.restore(state.vault, state.documents.read(d.uri), name, pass, p.name) }) { (r, created) ->
                    state.identitiesChanged()
                    dialog = SigningDialog.LinkRestored(r, created)
                }
            }
        }
        SigningDialog.ExportKeystore -> AlertDialog(
            onDismissRequest = { dialog = null },
            title = { Text("Export keystore file") },
            text = { Text("This saves the keystore file itself (not its passwords) where you choose. Anyone with the file and its " +
                "password can sign updates as you. Prefer an encrypted backup for safekeeping.") },
            confirmButton = { TextButton({ dialog = null; rec?.let { keystoreExporter.launch(it.keystoreFilename) } }) { Text("Export") } },
            dismissButton = { TextButton({ dialog = null }) { Text("Cancel") } },
        )
        is SigningDialog.Info -> AlertDialog(
            onDismissRequest = { dialog = null },
            title = { Text(d.title) },
            text = { Text(d.text, Modifier.testTag(d.tag)) },
            confirmButton = { TextButton({ dialog = null }) { Text("OK") } },
        )
        SigningDialog.BackUpNow -> AlertDialog(
            onDismissRequest = { dialog = null },
            title = { Text("Back up now?") },
            text = { Text("The new signing identity is ready but has NOT been backed up. Create an encrypted backup now?") },
            confirmButton = { TextButton({ dialog = SigningDialog.Backup }) { Text("Back Up") } },
            dismissButton = { TextButton({ dialog = null }, Modifier.testTag("backup_later")) { Text("Later") } },
        )
        is SigningDialog.LinkRestored -> AlertDialog(
            onDismissRequest = { dialog = null },
            title = { Text("Restore complete") },
            text = { Text((if (d.created) "Identity restored and verified." else "This identity is already in the vault; nothing was changed.") +
                "\n\n“${d.rec.label}”\nSHA-256 ${d.rec.fingerprintSha256}\n\nLink it to the open project?") },
            confirmButton = { TextButton({ dialog = null; link(d.rec.id) }) { Text("Link") } },
            dismissButton = { TextButton({ dialog = null }) { Text("Not now") } },
        )
        is SigningDialog.ConfirmReplace -> AlertDialog(
            onDismissRequest = { dialog = null },
            title = { Text("Change signing identity") },
            text = { Text("This project already has a different signing identity. Builds signed with another identity cannot update " +
                "existing installs. The current identity stays in the vault. Continue?") },
            confirmButton = { TextButton({ dialog = null; state.linkIdentity(d.id) }) { Text("Change") } },
            dismissButton = { TextButton({ dialog = null }) { Text("Cancel") } },
        )
    }
}

data class GenerateValues(val filename: String, val alias: String, val dname: String, val validityDays: Long)

@Composable
private fun DialogBody(content: @Composable () -> Unit) =
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) { content() }

@Composable
private fun GenerateDialog(state: AppState, existing: IdentityRecord?, onDismiss: () -> Unit, onGenerate: (GenerateValues) -> Unit) {
    val p = state.profile!!
    val (defFile, defAlias) = proposedNames(p.name)
    var filename by remember { mutableStateOf(defFile) }
    var alias by remember { mutableStateOf(defAlias) }
    var cn by remember { mutableStateOf(p.publisher) }
    var org by remember { mutableStateOf(p.publisher) }
    var country by remember { mutableStateOf("") }
    var years by remember { mutableStateOf("27") }
    var confirm by remember { mutableStateOf("") }
    var error by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Generate New Android Signing Identity") },
        text = {
            DialogBody {
                Text("Project: ${p.name.ifEmpty { "Untitled" }}")
                OutlinedTextField(filename, { filename = it }, Modifier.fillMaxWidth(), label = { Text("Keystore filename") }, singleLine = true)
                OutlinedTextField(alias, { alias = it }, Modifier.fillMaxWidth().testTag("gen_alias"), label = { Text("Key alias") }, singleLine = true)
                Text("Existing identity: " + (existing?.let { "Yes — “${it.label}”" } ?: "None"))
                OutlinedTextField(cn, { cn = it }, Modifier.fillMaxWidth(), label = { Text("Certificate name (CN)") }, singleLine = true)
                OutlinedTextField(org, { org = it }, Modifier.fillMaxWidth(), label = { Text("Organization (O)") }, singleLine = true)
                OutlinedTextField(country, { country = it.take(2) }, Modifier.fillMaxWidth(), label = { Text("Country code (optional)") }, singleLine = true)
                OutlinedTextField(years, { years = it.filter(Char::isDigit).take(2) }, Modifier.fillMaxWidth(), label = { Text("Validity (years, 26–50)") },
                    singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                Muted("Key: RSA $KEY_SIZE-bit, $SIGNATURE_ALGORITHM, PKCS12 keystore with one password for the keystore and the key. " +
                    "A strong random password is generated for you.")
                StatusBadge("Every future update of this app must be signed with this identity. If it is lost, installed copies can " +
                    "never be updated. Back it up immediately after generating it.", Badge.WARNING)
                if (existing != null) {
                    StatusBadge("This project already has a signing identity. Generating a new one does NOT delete it, but builds signed " +
                        "with the new identity cannot update installs signed with the old one.", Badge.ERROR)
                    OutlinedTextField(confirm, { confirm = it }, Modifier.fillMaxWidth().testTag("gen_confirm"), label = { Text("Type REPLACE to confirm") }, singleLine = true)
                }
                if (error.isNotEmpty()) StatusBadge(error, Badge.ERROR)
            }
        },
        confirmButton = {
            TextButton({
                val y = years.toIntOrNull() ?: 0
                error = when {
                    existing != null && confirm.trim() != "REPLACE" -> "Type REPLACE to confirm generating a replacement identity, or press Cancel."
                    filename.isBlank() || alias.isBlank() -> "Enter a keystore filename and key alias."
                    y !in 26..50 -> "Choose a validity between 26 and 50 years."
                    else -> ""
                }
                if (error.isEmpty()) {
                    val dname = runCatching { DName.build(cn, org, country = country) }
                    dname.onFailure { error = it.message ?: "Invalid certificate name." }
                    dname.onSuccess { onGenerate(GenerateValues(filename.trim(), alias.trim(), it, y * 365L + y / 4)) }
                }
            }, Modifier.testTag("gen_confirm_button")) { Text("Generate Identity") }
        },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun ImportDialog(state: AppState, bytes: ByteArray, name: String, onDismiss: () -> Unit, onImport: (String, String, String) -> Unit) {
    var storePw by remember { mutableStateOf("") }
    var aliases by remember { mutableStateOf<List<AliasEntry>?>(null) }
    var alias by remember { mutableStateOf("") }
    var samePw by remember { mutableStateOf(true) }
    var keyPw by remember { mutableStateOf("") }
    var error by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Import Existing Keystore") },
        text = {
            DialogBody {
                Muted("The keystore is copied into the app's protected vault. Your original file is not changed.")
                Mono(name)
                OutlinedTextField(storePw, { storePw = it; aliases = null }, Modifier.fillMaxWidth().testTag("import_store_pw"),
                    label = { Text("Keystore password") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
                SecondaryButton("Read Keystore", {
                    error = ""
                    runCatching { AndroidSigning.listAliases(bytes, storePw) }
                        .onSuccess { list -> aliases = list.filter { it.hasPrivateKey }; alias = aliases!!.firstOrNull()?.alias ?: ""
                            if (aliases!!.isEmpty()) error = "The keystore opened, but it contains no private keys that can sign apps." }
                        .onFailure { error = it.message ?: "The keystore could not be read." }
                })
                aliases?.takeIf { it.isNotEmpty() }?.let { list ->
                    Muted(if (list.size > 1) "Choose the key used to sign this app:" else "Key alias:")
                    for (a in list) Row(Modifier.fillMaxWidth().selectable(alias == a.alias) { alias = a.alias }, verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(alias == a.alias, { alias = a.alias }); Text(a.alias)
                    }
                    CheckRow("Key password is the same as the keystore password", samePw, "import_same_pw") { samePw = it }
                    if (!samePw) OutlinedTextField(keyPw, { keyPw = it }, Modifier.fillMaxWidth().testTag("import_key_pw"),
                        label = { Text("Key password") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
                }
                if (error.isNotEmpty()) StatusBadge(error, Badge.ERROR)
            }
        },
        confirmButton = {
            TextButton({
                when {
                    alias.isEmpty() -> error = "Read the keystore and choose a key alias first."
                    !samePw && keyPw.isEmpty() -> error = "Enter the key password."
                    else -> onImport(storePw, alias, if (samePw) storePw else keyPw)
                }
            }, enabled = aliases?.isNotEmpty() == true) { Text("Import") }
        },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun LinkDialog(records: List<IdentityRecord>, currentId: String, onDismiss: () -> Unit, onLink: (String) -> Unit) {
    var selected by remember { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Use Identity From Vault") },
        text = {
            DialogBody {
                Muted("Only link an identity that was used to sign this same application, otherwise updates will not install.")
                for (r in records) Row(Modifier.fillMaxWidth().selectable(selected == r.id) { selected = r.id }, verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected == r.id, { selected = r.id })
                    Column {
                        Text(r.label + if (r.id == currentId) " (current)" else "")
                        Mono("alias ${r.alias} · ${r.fingerprintSha256.take(23)}… · ${r.source}")
                    }
                }
            }
        },
        confirmButton = { TextButton({ selected?.let(onLink) }, enabled = selected != null) { Text("Link to Project") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun BackupPassphraseDialog(state: AppState, onDismiss: () -> Unit, onContinue: (String) -> Unit) {
    var pass1 by remember { mutableStateOf("") }
    var pass2 by remember { mutableStateOf("") }
    var visible by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Back Up Signing Identity") },
        text = {
            DialogBody {
                Muted("The backup contains the keystore and its passwords, encrypted with AES-256-GCM using a passphrase you choose. " +
                    "Save it somewhere other than this phone. Without the passphrase the backup cannot be opened.")
                val vt = if (visible) androidx.compose.ui.text.input.VisualTransformation.None else PasswordVisualTransformation()
                OutlinedTextField(pass1, { pass1 = it }, Modifier.fillMaxWidth().testTag("backup_pass1"), label = { Text("Passphrase") },
                    singleLine = true, visualTransformation = vt)
                OutlinedTextField(pass2, { pass2 = it }, Modifier.fillMaxWidth().testTag("backup_pass2"), label = { Text("Confirm passphrase") },
                    singleLine = true, visualTransformation = vt)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton({ val g = generatePassword().chunked(6).joinToString("-"); pass1 = g; pass2 = g; visible = true }) { Text("Generate") }
                    TextButton({ if (pass1.isNotEmpty()) state.clipboard.copy("Backup passphrase", pass1, sensitive = true) }) { Text("Copy") }
                }
                Muted("Use at least ${Backup.MIN_PASSPHRASE} characters. Write the passphrase down and keep it separately from the backup file. " +
                    "Next, choose where to save the file.")
                if (error.isNotEmpty()) StatusBadge(error, Badge.ERROR)
            }
        },
        confirmButton = {
            TextButton({
                error = Backup.validatePassphrase(pass1, pass2)
                if (error.isEmpty()) onContinue(pass1)
            }, Modifier.testTag("backup_continue")) { Text("Choose File…") }
        },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun PassphraseDialog(title: String, intro: String, onDismiss: () -> Unit, onOk: (String) -> Unit) {
    var pass by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            DialogBody {
                Muted(intro)
                OutlinedTextField(pass, { pass = it }, Modifier.fillMaxWidth().testTag("passphrase"), label = { Text("Backup passphrase") },
                    singleLine = true, visualTransformation = PasswordVisualTransformation())
            }
        },
        confirmButton = { TextButton({ onOk(pass) }, enabled = pass.isNotEmpty()) { Text("Continue") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancel") } },
    )
}
