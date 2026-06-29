// src-tauri/src/main.rs
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

/// Try to launch an editor via CLI command (checks PATH).
fn try_editor_cli(name: &str, goto_target: &str) -> bool {
    std::process::Command::new(name)
        .args(["--goto", goto_target])
        .spawn()
        .is_ok()
}

/// On Windows, scan common install locations for editor executables
/// and try to launch with `--goto`. Handles the case where the editor
/// is installed but not in PATH and the protocol handler isn't registered.
#[cfg(target_os = "windows")]
fn try_editor_install_paths(goto_target: &str) -> bool {
    let local_appdata = std::env::var("LOCALAPPDATA").unwrap_or_default();
    let program_files = std::env::var("ProgramFiles").unwrap_or_default();

    let candidates: &[&str] = &[
        // Cursor
        &format!("{}\\Programs\\Cursor\\Cursor.exe", local_appdata),
        &format!("{}\\cursor\\Cursor.exe", local_appdata),
        // VS Code
        &format!("{}\\Programs\\Microsoft VS Code\\Code.exe", local_appdata),
        &format!("{}\\Microsoft VS Code\\Code.exe", program_files),
        // VS Code Insiders
        &format!("{}\\Programs\\Microsoft VS Code Insiders\\Code - Insiders.exe", local_appdata),
    ];

    for exe in candidates {
        if std::path::Path::new(exe).exists() {
            if std::process::Command::new(exe)
                .args(["--goto", goto_target])
                .spawn()
                .is_ok()
            {
                return true;
            }
        }
    }
    false
}

#[cfg(not(target_os = "windows"))]
fn try_editor_install_paths(_goto_target: &str) -> bool {
    false
}

#[tauri::command]
fn open_in_editor(path: String, line: u32) -> Result<(), String> {
    let goto_target = format!("{}:{}", path, line);

    // ── 1. Try CLI in PATH (`code --goto`, `cursor --goto`, etc.) ──
    for editor in &["cursor", "code", "code-insiders"] {
        if try_editor_cli(editor, &goto_target) {
            return Ok(());
        }
    }

    // ── 2. Windows: scan common install locations ──
    if try_editor_install_paths(&goto_target) {
        return Ok(());
    }

    // ── 3. Fallback: URL protocol handlers ──
    let vscode_url = format!("vscode://file/{}:{}", path, line);
    let cursor_url = format!("cursor://file/{}:{}", path, line);

    #[cfg(target_os = "windows")]
    {
        for url in &[&vscode_url, &cursor_url] {
            if std::process::Command::new("cmd")
                .args(["/c", "start", "", url])
                .spawn()
                .is_ok()
            {
                return Ok(());
            }
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        for url in &[&vscode_url, &cursor_url] {
            if std::process::Command::new("open")
                .arg(url)
                .spawn()
                .is_ok()
            {
                return Ok(());
            }
        }
    }

    // ── 4. Last resort: open file with default app (no line navigation) ──
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/c", "start", "", &path])
            .spawn()
            .map_err(|e| format!("无法打开文件: {}", e))?;
    }
    #[cfg(not(target_os = "windows"))]
    {
        std::process::Command::new("open")
            .arg(&path)
            .spawn()
            .map_err(|e| format!("无法打开文件: {}", e))?;
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
