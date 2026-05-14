package com.example.androidapp

import android.app.Activity
import android.os.Bundle
import com.example.shared.Greeter

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Greeter().greet()
    }
}
