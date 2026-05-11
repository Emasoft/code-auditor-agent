// Arduino sketch fixture — covers the four entry-point shapes the
// firmware_arduino discoverer is expected to recognise.

#define BUTTON_PIN 2

volatile bool button_pressed = false;

// ISR triggered by a falling edge on the button pin.
void buttonHandler() {
  button_pressed = true;
}

// Serial RX callback — invoked when bytes are available on UART0.
void serialHandler() {
  // Drain Serial RX buffer; production code would copy into a ring.
  while (Serial.available()) {
    Serial.read();
  }
}

// One-time hardware init at power-on / reset.
void setup() {
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  Serial.begin(115200);
  attachInterrupt(digitalPinToInterrupt(BUTTON_PIN), buttonHandler, FALLING);
  Serial.onReceive(serialHandler);
}

// Cooperative main loop — runs forever after setup() returns.
void loop() {
  if (button_pressed) {
    button_pressed = false;
    Serial.println("button pressed");
  }
  delay(10);
}
