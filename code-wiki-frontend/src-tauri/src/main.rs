// src-tauri/src/main.rs
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[tauri::command]
fn open_in_editor(path: String, line: u32) -> Result<(), String> {
    // Try to open via VS Code / Cursor protocol
    let vscode_url = format!("vscode://file/{}:{}", path, line);
    let cursor_url = format!("cursor://file/{}:{}", path, line);

    // On Windows, use the shell to open the URL
    #[cfg(target_os = "windows")]
    {
        // Try Cursor first, then VS Code
        if std::process::Command::new("cmd")
            .args(["/c", "start", "", &cursor_url])
            .spawn()
            .is_ok()
        {
            return Ok(());
        }
        if std::process::Command::new("cmd")
            .args(["/c", "start", "", &vscode_url])
            .spawn()
            .is_ok()
        {
            return Ok(());
        }
    }

    // macOS / Linux
    #[cfg(not(target_os = "windows"))]
    {
        for editor in &["cursor", "code", "code-insiders"] {
            if std::process::Command::new(editor)
                .args(["--goto", &format!("{}:{}", path, line)])
                .spawn()
                .is_ok()
            {
                return Ok(());
            }
        }
    }

    // Fallback: open with system default
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/c", "start", "", &path])
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(not(target_os = "windows"))]
    {
        std::process::Command::new("open")
            .arg(&path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }

    Ok(())
}

/// Read a file from the local filesystem (used in Tauri desktop mode).
/// Takes the repo root path and a relative file path, joins them safely,
/// and returns the file content as a string.
#[tauri::command]
fn read_file_content(repo_path: String, file_path: String) -> Result<String, String> {
    let base = std::path::Path::new(&repo_path);
    if !base.is_dir() {
        return Err("仓库路径不存在或不是目录".into());
    }

    // Resolve the relative path against the repo root
    let full = base.join(&file_path);
    let canonical = full.canonicalize().map_err(|e| format!("无法解析路径: {}", e))?;

    // Security: ensure the resolved path is still within the repo root
    let repo_canonical = base.canonicalize().map_err(|e| format!("无法解析仓库路径: {}", e))?;
    if !canonical.starts_with(&repo_canonical) {
        return Err("路径越权".into());
    }

    // Read the file
    let content = std::fs::read_to_string(&canonical)
        .map_err(|e| format!("读取文件失败: {}", e))?;

    Ok(content)
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![open_in_editor, read_file_content])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
