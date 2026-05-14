package com.example.shared

expect fun platformName(): String

expect fun deviceId(): String

expect class Greeter() {
    fun greet(): String
}
