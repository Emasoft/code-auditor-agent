#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    MainWindow(QWidget *parent = nullptr);
public slots:
    void onButtonClicked();
    void onFileOpened();
private:
    int counter;
};

class SettingsDialog : public QDialog {
    Q_OBJECT
public:
    SettingsDialog(QWidget *parent = nullptr);
public slots:
    void onApplyPressed();
};

#endif
