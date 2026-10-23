package com.hotatticgames.buildsigning.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.hotatticgames.buildsigning.AppState
import com.hotatticgames.buildsigning.Level
import kotlinx.coroutines.launch

enum class Screen(val title: String, val icon: ImageVector, val needsProject: Boolean) {
    PROJECTS("Projects", Icons.Filled.Home, false),
    DETAILS("Application Details", Icons.Filled.Edit, true),
    PLATFORMS("Platforms & Stores", Icons.Filled.Build, true),
    SIGNING("Signing Identities", Icons.Filled.Lock, true),
    SECRETS("GitHub Secrets", Icons.AutoMirrored.Filled.List, true),
    PROMPT("Generated Prompt", Icons.AutoMirrored.Filled.Send, true),
    SETTINGS("Settings", Icons.Filled.Settings, false),
}

/** Runs [action] immediately, or after asking to save/discard when the open project has unsaved changes. */
class UnsavedGuard {
    var pending by mutableStateOf<(() -> Unit)?>(null)
    fun run(state: AppState, action: () -> Unit) { if (state.dirty) pending = action else action() }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App(state: AppState) {
    var screen by rememberSaveable { mutableStateOf(if (state.profile != null) Screen.DETAILS else Screen.PROJECTS) }
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }
    val guard = remember { UnsavedGuard() }
    state.revision  // recompose on edits

    val msg = state.message
    LaunchedEffect(msg?.id) { msg?.let { snackbar.showSnackbar(it.text, withDismissAction = true) } }
    if (state.profile == null && screen.needsProject) screen = Screen.PROJECTS

    BackHandler(enabled = screen != Screen.PROJECTS) { screen = Screen.PROJECTS }

    ModalNavigationDrawer(
        drawerState = drawer,
        drawerContent = {
            ModalDrawerSheet(drawerContainerColor = Palette.panel) {
                Text("HOT ATTIC GAMES", Modifier.padding(start = 24.dp, top = 24.dp), color = Palette.accent, fontWeight = FontWeight.Bold)
                Text("Build & Signing Manager", Modifier.padding(start = 24.dp, bottom = 16.dp), color = Palette.muted)
                for (s in Screen.entries) {
                    val enabled = !s.needsProject || state.profile != null
                    NavigationDrawerItem(
                        label = { Text(s.title, color = if (enabled) Palette.text else Palette.muted.copy(alpha = 0.5f)) },
                        icon = { Icon(s.icon, null) },
                        selected = s == screen,
                        onClick = {
                            if (enabled) { screen = s; scope.launch { drawer.close() } }
                            else state.say("Open or create a project first.")
                        },
                        modifier = Modifier.padding(horizontal = 12.dp).testTag("nav_${s.name}"),
                    )
                }
            }
        },
    ) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = {
                        Column {
                            Text(screen.title, fontSize = 18.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            val p = state.profile
                            Text(
                                if (p == null) "No project open" else (p.name.ifEmpty { "Untitled project" } + if (state.dirty) "  ● Unsaved" else ""),
                                fontSize = 13.sp, color = if (state.dirty) Palette.warning else Palette.muted,
                                maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.testTag("project_title"),
                            )
                        }
                    },
                    navigationIcon = {
                        IconButton({ scope.launch { drawer.open() } }, Modifier.testTag("menu")) { Icon(Icons.Filled.Menu, "Menu") }
                    },
                    actions = {
                        if (state.profile != null)
                            TextButton({ state.save() }, enabled = state.dirty, modifier = Modifier.testTag("save")) { Text("Save") }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = Palette.panel),
                )
            },
            snackbarHost = {
                SnackbarHost(snackbar) { data ->
                    val color = when (msg?.level) {
                        Level.SUCCESS -> Palette.success; Level.WARNING -> Palette.warning
                        Level.ERROR -> Palette.error; else -> Palette.text
                    }
                    Snackbar(data, containerColor = Palette.panelAlt, contentColor = color)
                }
            },
            containerColor = Palette.bg,
        ) { padding ->
            Box(Modifier.padding(padding).fillMaxSize()) {
                Column {
                    state.busy?.let {
                        LinearProgressIndicator(Modifier.fillMaxWidth())
                        Text(it, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), color = Palette.muted, fontSize = 13.sp)
                    }
                    when (screen) {
                        Screen.PROJECTS -> ProjectsScreen(state, guard) { screen = Screen.DETAILS }
                        Screen.DETAILS -> DetailsScreen(state)
                        Screen.PLATFORMS -> PlatformsScreen(state)
                        Screen.SIGNING -> SigningScreen(state)
                        Screen.SECRETS -> SecretsScreen(state)
                        Screen.PROMPT -> PromptScreen(state)
                        Screen.SETTINGS -> SettingsScreen(state)
                    }
                }
            }
        }
    }

    guard.pending?.let { action ->
        AlertDialog(
            onDismissRequest = { guard.pending = null },
            title = { Text("Unsaved changes") },
            text = { Text("“${state.profile?.name?.ifEmpty { "Untitled" }}” has unsaved changes. Save them first?") },
            confirmButton = {
                TextButton({ guard.pending = null; if (state.save()) action() }, Modifier.testTag("unsaved_save")) { Text("Save") }
            },
            dismissButton = {
                Row2 {
                    TextButton({ guard.pending = null }) { Text("Cancel") }
                    TextButton({ guard.pending = null; action() }, Modifier.testTag("unsaved_discard")) { Text("Discard") }
                }
            },
        )
    }
}

@Composable
private fun Row2(content: @Composable () -> Unit) = androidx.compose.foundation.layout.Row { content() }
