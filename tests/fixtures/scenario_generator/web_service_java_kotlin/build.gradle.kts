// fixture for web_service_java_kotlin
// Ships alongside pom.xml + build.gradle so the detect_software_type
// fingerprint (AND-across-specs) fires deterministically.
plugins {
    id("org.springframework.boot") version "3.2.0"
    id("io.spring.dependency-management") version "1.1.0"
    kotlin("jvm") version "1.9.0"
}

group = "com.example.fixture"
version = "0.1.0"

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web")
}
