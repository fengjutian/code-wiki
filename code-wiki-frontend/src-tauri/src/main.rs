// src-tauri/src/main.rs
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashMap;
use std::sync::Mutex;
use tauri::Emitter;
use notify::{Event, EventKind, RecursiveMode, Watcher};

/// Global watcher registry: watch_id → (watcher, dir_path)
static WATCHERS: Mutex<Option<HashMap<String, (notify::RecommendedWatcher, String)>>> = Mutex::new(None);

fn watchers_map() -> std::sync::MutexGuard<'static, Option<HashMap<String, (notify::RecommendedWatcher, String)>>> {
    let mut guard = WATCHERS.lock().unwrap();
    if guard.is_none() {
        *guard = Some(HashMap::new());
    }
    guard
}

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
/// Takes an absolute file path and returns the file content as a string.
#[tauri::command]
fn read_document_file(path: String) -> Result<String, String> {
    let full = std::path::Path::new(&path);
    // Security: verify the path exists and is a file
    if !full.exists() {
        return Err(format!("文件不存在: {}", path));
    }
    if !full.is_file() {
        return Err("路径不是文件".into());
    }
    // Limit to 200KB for chat context
    let metadata = std::fs::metadata(full).map_err(|e| format!("无法读取文件元数据: {}", e))?;
    let max_bytes: u64 = 200 * 1024;
    let len = metadata.len();
    let content = if len > max_bytes {
        return Err(format!("文件过大 ({:.1}KB)，限制 {:.1}KB", len as f64 / 1024.0, max_bytes as f64 / 1024.0));
    } else {
        std::fs::read_to_string(full).map_err(|e| format!("读取文件失败: {}", e))?
    };
    Ok(content)
}

/// Read all text files from a directory recursively.
/// Returns an array of {name, path, content} up to limits.
#[derive(serde::Serialize)]
struct DirFile {
    name: String,
    path: String,
    content: String,
}

#[tauri::command]
fn read_directory_files(dir_path: String) -> Result<Vec<DirFile>, String> {
    let root = std::path::Path::new(&dir_path);
    if !root.exists() {
        return Err(format!("目录不存在: {}", dir_path));
    }
    if !root.is_dir() {
        return Err("路径不是目录".into());
    }

    let max_files: usize = 200;
    let max_file_bytes: u64 = 150 * 1024;   // per file
    let max_total_bytes: u64 = 2 * 1024 * 1024;  // 2MB total

    let mut results: Vec<DirFile> = Vec::new();
    let mut total_bytes: u64 = 0;

    // Common text extensions — skip binaries
    let text_exts: std::collections::HashSet<&str> = [
        "txt", "md", "csv", "json", "xml", "yaml", "yml", "log",
        "html", "htm", "css", "scss", "less",
        "py", "js", "ts", "tsx", "jsx", "mjs", "cjs",
        "rs", "go", "java", "kt", "swift", "c", "cpp", "h", "hpp",
        "rb", "php", "sh", "bash", "zsh", "fish",
        "toml", "ini", "cfg", "conf", "env", "gitignore", "dockerignore",
        "sql", "graphql", "proto",
    ].iter().cloned().collect();

    fn is_text_file(path: &std::path::Path, text_exts: &std::collections::HashSet<&str>) -> bool {
        if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
            return text_exts.contains(&ext.to_lowercase().as_str());
        }
        // Files without extension (Dockerfile, Makefile, LICENSE, etc.) — treat as text
        true
    }

    fn walk(
        dir: &std::path::Path,
        root: &std::path::Path,
        results: &mut Vec<DirFile>,
        total_bytes: &mut u64,
        max_files: usize,
        max_file_bytes: u64,
        max_total_bytes: u64,
        text_exts: &std::collections::HashSet<&str>,
    ) -> Result<(), String> {
        if results.len() >= max_files || *total_bytes >= max_total_bytes {
            return Ok(());
        }

        let entries = std::fs::read_dir(dir).map_err(|e| format!("读取目录失败: {}", e))?;
        for entry in entries.flatten() {
            if results.len() >= max_files || *total_bytes >= max_total_bytes {
                break;
            }
            let path = entry.path();
            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("?").to_string();
            // Skip hidden directories, but allow hidden files with text extensions
            if name.starts_with('.') {
                if path.is_dir() {
                    continue; // skip .git, .code-wiki, etc.
                }
                // Allow hidden text files (.env, .gitignore, .dockerignore)
                if !is_text_file(&path, text_exts) {
                    continue;
                }
            }
            if path.is_dir() {
                walk(&path, root, results, total_bytes, max_files, max_file_bytes, max_total_bytes, text_exts)?;
            } else if path.is_file() && is_text_file(&path, text_exts) {
                let metadata = std::fs::metadata(&path).map_err(|e| format!("无法读取元数据: {}", e))?;
                if metadata.len() > max_file_bytes {
                    continue; // skip large files
                }
                match std::fs::read_to_string(&path) {
                    Ok(content) => {
                        *total_bytes += content.len() as u64;
                        let rel_path = path.strip_prefix(root).unwrap_or(&path).to_string_lossy().to_string();
                        results.push(DirFile { name, path: rel_path, content });
                    }
                    Err(_) => continue, // skip unreadable
                }
            }
        }
        Ok(())
    }

    walk(root, root, &mut results, &mut total_bytes, max_files, max_file_bytes, max_total_bytes, &text_exts)?;
    Ok(results)
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

/// Start watching a directory for file changes.
/// Returns a watch_id that can be used to stop watching.
/// Emits `dir-changed` event to the frontend when files change.
#[tauri::command]
fn start_watch_directory(app: tauri::AppHandle, dir_path: String) -> Result<String, String> {
    let root = std::path::Path::new(&dir_path);
    if !root.is_dir() {
        return Err("路径不是目录".into());
    }

    let watch_id = format!("watch_{}", std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis());

    let dir_path_clone = dir_path.clone();
    let app_clone = app.clone();

    let mut watcher = notify::recommended_watcher(move |res: Result<Event, notify::Error>| {
        match res {
            Ok(event) => {
                // Only react to meaningful file changes (create/modify/remove)
                let is_relevant = matches!(
                    event.kind,
                    EventKind::Create(_) | EventKind::Modify(_) | EventKind::Remove(_)
                );
                if is_relevant {
                    // Debounce: emit event so frontend re-reads
                    let _ = app_clone.emit("dir-changed", &dir_path_clone);
                }
            }
            Err(e) => {
                eprintln!("watch error: {:?}", e);
            }
        }
    }).map_err(|e| format!("创建文件监听器失败: {}", e))?;

    watcher
        .watch(root, RecursiveMode::Recursive)
        .map_err(|e| format!("开始监听失败: {}", e))?;

    let mut map = watchers_map();
    map.as_mut().unwrap().insert(watch_id.clone(), (watcher, dir_path));

    Ok(watch_id)
}

/// Stop watching a directory.
#[tauri::command]
fn stop_watch_directory(watch_id: String) -> Result<(), String> {
    let mut map = watchers_map();
    if let Some(m) = map.as_mut() {
        m.remove(&watch_id);
    }
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![open_in_editor, read_file_content, read_document_file, read_directory_files, start_watch_directory, stop_watch_directory])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
