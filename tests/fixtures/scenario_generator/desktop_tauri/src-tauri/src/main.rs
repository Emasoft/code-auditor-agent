// Demo Tauri main process.

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}!", name)
}

#[tauri::command]
async fn save_file(path: String, contents: String) -> Result<(), String> {
    std::fs::write(&path, contents).map_err(|e| e.to_string())
}

#[tauri::command(rename_all = "snake_case")]
pub fn list_files(directory: String) -> Vec<String> {
    let _ = directory;
    Vec::new()
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![greet, save_file, list_files])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
