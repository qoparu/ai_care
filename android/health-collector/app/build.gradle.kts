plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.aicare.collector"
    compileSdk = 35

    buildFeatures {
        compose = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }

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
    val composeBom = platform("androidx.compose:compose-bom:2024.09.00")
    implementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")

    // --- Route A: Health Connect (no Samsung approval needed) -------------
    implementation("androidx.health.connect:connect-client:1.1.0-alpha10")

    // --- Route B: Samsung Health Data SDK --------------------------------
    // Not a Maven artifact — download the .aar from developer.samsung.com and
    // drop it into app/libs/ (see app/libs/README.md). Picked up automatically:
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.aar"))))
    // The SDK's own samples list gson as a runtime dependency:
    implementation("com.google.code.gson:gson:2.10.1")
}
