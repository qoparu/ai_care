plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.aicare.collector"
    compileSdk = 35

    defaultConfig {
        // ---------------------------------------------------------------
        // THE package name. Single source of truth.
        //
        // This exact string is what goes in Samsung Health's developer-mode
        // "app package name" field, if that route is used. It must match
        // character for character — Samsung matches on the literal string.
        //
        // Changing it here means changing it in Samsung Health too.
        // ---------------------------------------------------------------
        applicationId = "com.aicare.collector"

        // Health Connect requires 26+; Samsung Health Data SDK is higher.
        minSdk = 28
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")

    // --- Route A: Health Connect (no Samsung approval needed) -------------
    implementation("androidx.health.connect:connect-client:1.1.0-alpha10")

    // --- Route B: Samsung Health Data SDK --------------------------------
    // Not a Maven artifact — the SDK ships as an .aar you download from
    // developer.samsung.com and drop into app/libs/. Uncomment when used:
    // implementation(files("libs/samsung-health-data-api-1.0.0.aar"))
}
