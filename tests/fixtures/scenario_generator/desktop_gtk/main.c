// Demo GTK application entry point.
#include <gtk/gtk.h>

static void on_button_clicked(GtkButton *button, gpointer user_data) {
    (void)button;
    (void)user_data;
}

static void on_window_destroy(GtkWidget *widget, gpointer user_data) {
    (void)widget;
    (void)user_data;
}

static void activate(GtkApplication *app, gpointer user_data) {
    (void)user_data;
    GtkWidget *window = gtk_application_window_new(app);
    GtkWidget *btn = gtk_button_new_with_label("Click me");
    g_signal_connect(btn, "clicked", G_CALLBACK(on_button_clicked), NULL);
    g_signal_connect(window, "destroy", G_CALLBACK(on_window_destroy), NULL);
    gtk_window_set_child(GTK_WINDOW(window), btn);
    gtk_window_present(GTK_WINDOW(window));
}

int main(int argc, char **argv) {
    GtkApplication *app = gtk_application_new("org.example.DemoGtk", G_APPLICATION_FLAGS_NONE);
    g_signal_connect(app, "activate", G_CALLBACK(activate), NULL);
    return g_application_run(G_APPLICATION(app), argc, argv);
}
