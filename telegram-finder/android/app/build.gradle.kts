plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

// Optional release signing:  -PksFile=... -PksPass=... -PksAlias=...
val ksFile = findProperty("ksFile") as String?

android {
    namespace = "app.tgfinder"
    compileSdk = 34
    defaultConfig {
        applicationId = "app.tgfinder"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
    }
    signingConfigs {
        if (ksFile != null) create("release") {
            storeFile = file(ksFile)
            storePassword = findProperty("ksPass") as String
            keyAlias = findProperty("ksAlias") as String
            keyPassword = findProperty("ksPass") as String
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

chaquopy {
    defaultConfig {
        version = "3.11"
        pip { install("telethon") }
    }
}
