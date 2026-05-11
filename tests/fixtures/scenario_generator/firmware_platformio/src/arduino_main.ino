// Arduino sketch entry points — used by firmware_platformio fixture.

const int BUTTON_PIN = 2;
volatile bool button_pressed = false;

// ISR invoked when the button line goes LOW.
void on_button() {
  button_pressed = true;
}

// Standard Arduino setup: configures pins and the ISR.
void setup() {
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(BUTTON_PIN), on_button, FALLING);
}

// Main loop: poll the flag and react.
void loop() {
  if (button_pressed) {
    button_pressed = false;
    // user code would go here
  }
}
