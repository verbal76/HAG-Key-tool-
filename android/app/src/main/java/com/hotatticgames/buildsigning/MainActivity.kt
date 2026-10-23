package com.hotatticgames.buildsigning

import android.app.Application
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.hotatticgames.buildsigning.ui.App
import com.hotatticgames.buildsigning.ui.AppTheme

class MainViewModel(app: Application) : AndroidViewModel(app) {
    val state = AppState(app, AndroidKeystoreProtector(), viewModelScope)
}

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Passwords and keys are shown on some screens: keep them out of screenshots and the recents preview.
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        setContent { AppTheme { App(vm.state) } }
    }

    override fun onResume() {
        super.onResume()
        vm.state.clipboard.clearPending()
    }
}
