pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
    plugins {
        id("com.android.application") version "8.7.3"
        id("org.jetbrains.kotlin.android") version "2.0.21"
        id("org.jetbrains.kotlin.jvm") version "2.0.21"
        id("org.jetbrains.kotlin.plugin.compose") version "2.0.21"
        id("org.jetbrains.kotlin.plugin.serialization") version "2.0.21"
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "HotAtticBuildSigningManager"
include(":core")
// The Android modules need Google's Maven repository. Set HAGBSM_CORE_ONLY=1 to build only
// the pure-Kotlin core where that repository is unavailable.
if (System.getenv("HAGBSM_CORE_ONLY") == null) {
    include(":apk", ":app")
}
