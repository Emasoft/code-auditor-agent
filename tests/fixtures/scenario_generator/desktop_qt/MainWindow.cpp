#include "MainWindow.h"
#include <QPushButton>

MainWindow::MainWindow(QWidget *parent) : QMainWindow(parent), counter(0) {
    auto *btn = new QPushButton("Click me", this);
    setCentralWidget(btn);
    connect(btn, &QPushButton::clicked, this, &MainWindow::onButtonClicked);
}

void MainWindow::onButtonClicked() {
    counter++;
}

void MainWindow::onFileOpened() {
    counter = 0;
}

SettingsDialog::SettingsDialog(QWidget *parent) : QDialog(parent) {}

void SettingsDialog::onApplyPressed() {}
