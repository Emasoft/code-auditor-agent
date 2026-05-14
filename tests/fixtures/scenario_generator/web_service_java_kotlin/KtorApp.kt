package com.example.fixture

import io.ktor.server.application.*
import io.ktor.server.response.*
import io.ktor.server.routing.*

fun Application.module() {
    routing {
        /**
         * Return server health status.
         */
        get("/health") {
            call.respondText("ok")
        }
        /**
         * Return current server version.
         */
        get("/version") {
            call.respondText("0.1.0")
        }
    }
}
