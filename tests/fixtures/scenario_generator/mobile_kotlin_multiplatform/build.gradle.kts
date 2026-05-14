// fixture for mobile_kotlin_multiplatform
plugins {
    id("kotlin-multiplatform") version "1.9.0"
}

kotlin {
    androidTarget()
    iosX64()
    iosArm64()
    sourceSets {
        val commonMain by getting
        val androidMain by getting
        val iosMain by getting
    }
}
