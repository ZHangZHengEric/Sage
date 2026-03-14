#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use tauri::{
    menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem},
    path::BaseDirectory,
    tray::{MouseButton, TrayIcon, TrayIconBuilder, TrayIconEvent},
    image::Image,
    Emitter, Manager, WindowEvent,
};
#[cfg(target_os = "macos")]
use cocoa::appkit::{NSApp, NSApplication, NSApplicationActivationPolicy};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Mutex;
use sysinfo::{System, Pid};
use serde::{Deserialize, Serialize};

const MAX_MEMORY_MB: u64 = 2048;

struct SidecarPid(Mutex<Option<u32>>);
struct Tray(Mutex<Option<TrayIcon>>);

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
enum CloseAction {
    HideToTray,
    ExitApp,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ClosePreference {
    action: CloseAction,
    remember_choice: bool,
}

struct ClosePreferenceState(Mutex<Option<ClosePreference>>);

const SAGE_ENV_FILE: &str = ".sage_env";

fn get_sage_root_dir() -> PathBuf {
    let home_dir = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_default();
    PathBuf::from(home_dir).join(".sage")
}

const CLOSE_PREFERENCE_FILE: &str = "close_preference.json";

fn get_close_preference_path() -> PathBuf {
    get_sage_root_dir().join(CLOSE_PREFERENCE_FILE)
}

fn load_close_preference() -> Option<ClosePreference> {
    let path = get_close_preference_path();
    println!("Loading close preference from: {:?}", path);
    if !path.exists() {
        println!("Close preference file does not exist");
        return None;
    }
    match std::fs::read_to_string(&path) {
        Ok(content) => {
            println!("Close preference file content: {}", content);
            match serde_json::from_str(&content) {
                Ok(pref) => {
                    println!("Close preference loaded successfully: {:?}", pref);
                    Some(pref)
                }
                Err(e) => {
                    eprintln!("Failed to parse close preference: {}", e);
                    None
                }
            }
        }
        Err(e) => {
            eprintln!("Failed to read close preference file: {}", e);
            None
        }
    }
}

fn save_close_preference(preference: &ClosePreference) -> Result<(), String> {
    let sage_root = get_sage_root_dir();
    println!("Saving close preference to: {:?}", sage_root);
    if !sage_root.exists() {
        println!("Creating .sage directory");
        std::fs::create_dir_all(&sage_root)
            .map_err(|e| format!("Failed to create .sage directory: {}", e))?;
    }
    let path = get_close_preference_path();
    println!("Preference file path: {:?}", path);
    let content = serde_json::to_string(preference)
        .map_err(|e| format!("Failed to serialize preference: {}", e))?;
    println!("Preference content: {}", content);
    std::fs::write(&path, content)
        .map_err(|e| format!("Failed to write preference file: {}", e))?;
    println!("Preference saved successfully");
    Ok(())
}

fn load_sage_env_file() {
    let sage_root = get_sage_root_dir();
    let env_file_path = sage_root.join(SAGE_ENV_FILE);
    
    if !env_file_path.exists() {
        println!(".sage_env file not found at {:?}", env_file_path);
        return;
    }
    
    match std::fs::read_to_string(&env_file_path) {
        Ok(content) => {
            println!("Loading .sage_env from {:?}", env_file_path);
            for line in content.lines() {
                let line = line.trim();
                if line.is_empty() || line.starts_with('#') {
                    continue;
                }
                
                if let Some((key, value)) = line.split_once('=') {
                    let key = key.trim();
                    let value = value.trim();
                    if !key.is_empty() && !value.is_empty() {
                        std::env::set_var(key, value);
                        println!("Set from .sage_env: {}={}", key, value);
                    }
                }
            }
            println!("Loaded .sage_env successfully");
        }
        Err(e) => {
            eprintln!("Failed to read .sage_env file: {}", e);
        }
    }
}

#[derive(Clone, serde::Serialize)]
struct Payload {
    port: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CloseDialogResult {
    action: String, // "hide" or "exit"
    remember: bool,
}

#[tauri::command(async)]
fn get_server_port() -> Option<u16> {
    std::env::var("SAGE_PORT").ok().and_then(|p| p.parse().ok())
}

#[tauri::command]
fn handle_close_dialog_result(result: CloseDialogResult, app: tauri::AppHandle) {
    let action = result.action;
    let remember = result.remember;

    if remember {
        let close_action = if action == "exit" {
            CloseAction::ExitApp
        } else {
            CloseAction::HideToTray
        };
        match save_close_preference(&ClosePreference {
            action: close_action,
            remember_choice: true,
        }) {
            Ok(_) => println!("Close preference saved successfully"),
            Err(e) => eprintln!("Failed to save close preference: {}", e),
        }
    } else {
        println!("User chose not to remember preference");
    }

    if action == "exit" {
        if let Some(sidecar_state) = app.try_state::<SidecarPid>() {
            let mut pid_guard = sidecar_state.0.lock().unwrap();
            if let Some(pid) = *pid_guard {
                #[cfg(unix)]
                std::process::Command::new("kill")
                    .arg(pid.to_string())
                    .output()
                    .ok();
                #[cfg(windows)]
                std::process::Command::new("taskkill")
                    .args(["/F", "/PID", &pid.to_string()])
                    .output()
                    .ok();
                *pid_guard = None;
            }
        }
        app.exit(0);
    } else {
        // hide to tray
        #[cfg(target_os = "macos")]
        {
            set_activation_policy_accessory();
            let _ = app.hide();
        }
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.hide();
        }
    }
}

#[tauri::command(async)]
fn get_system_proxy() -> Option<String> {
    // 1. Try environment variables first
    if let Ok(proxy) = std::env::var("HTTP_PROXY")
        .or_else(|_| std::env::var("http_proxy"))
        .or_else(|_| std::env::var("HTTPS_PROXY"))
        .or_else(|_| std::env::var("https_proxy"))
        .or_else(|_| std::env::var("ALL_PROXY"))
        .or_else(|_| std::env::var("all_proxy")) 
    {
        return Some(proxy);
    }

    // 2. macOS specific check using scutil
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("scutil").arg("--proxy").output() {
            let output_str = String::from_utf8_lossy(&output.stdout);
            
            let mut host = String::new();
            let mut port = String::new();
            let mut enabled = false;
            
            for line in output_str.lines() {
                let line = line.trim();
                if line.starts_with("HTTPEnable") && line.contains("1") {
                    enabled = true;
                }
                if line.starts_with("HTTPProxy") {
                    if let Some(val) = line.split(':').nth(1) {
                        host = val.trim().to_string();
                    }
                }
                if line.starts_with("HTTPPort") {
                     if let Some(val) = line.split(':').nth(1) {
                        port = val.trim().to_string();
                    }
                }
            }
            
            if enabled && !host.is_empty() && !port.is_empty() {
                return Some(format!("http://{}:{}", host, port));
            }
        }
    }

    // 3. Windows specific check using netsh
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("netsh").args(["winhttp", "show", "proxy"]).output() {
            let output_str = String::from_utf8_lossy(&output.stdout);
            // Check if proxy is enabled (not "Direct access")
            if !output_str.contains("Direct access") {
                // Try to extract proxy server address
                for line in output_str.lines() {
                    let line = line.trim();
                    if line.starts_with("Proxy Server(s)") || line.starts_with("Proxy Server") {
                        if let Some(proxy_part) = line.split(':').nth(1) {
                            let proxy = proxy_part.trim().to_string();
                            if !proxy.is_empty() {
                                // Add http:// prefix if not present
                                if !proxy.starts_with("http://") && !proxy.starts_with("https://") {
                                    return Some(format!("http://{}", proxy));
                                }
                                return Some(proxy);
                            }
                        }
                    }
                }
            }
        }
    }

    None
}

#[tauri::command]
fn get_sage_env_content() -> Result<String, String> {
    let sage_root = get_sage_root_dir();
    let env_file_path = sage_root.join(SAGE_ENV_FILE);
    
    if !env_file_path.exists() {
        return Ok(String::new());
    }
    
    std::fs::read_to_string(&env_file_path)
        .map_err(|e| format!("Failed to read .sage_env file: {}", e))
}

#[tauri::command]
fn save_sage_env_content(content: String) -> Result<(), String> {
    let sage_root = get_sage_root_dir();
    
    if !sage_root.exists() {
        std::fs::create_dir_all(&sage_root)
            .map_err(|e| format!("Failed to create .sage directory: {}", e))?;
    }
    
    let env_file_path = sage_root.join(SAGE_ENV_FILE);
    
    std::fs::write(&env_file_path, content)
        .map_err(|e| format!("Failed to write .sage_env file: {}", e))
}

#[cfg(target_os = "macos")]
fn set_activation_policy_accessory() {
    unsafe {
        let app = NSApp();
        app.setActivationPolicy_(
            NSApplicationActivationPolicy::NSApplicationActivationPolicyAccessory,
        );
    }
}

#[cfg(target_os = "macos")]
fn set_activation_policy_regular() {
    unsafe {
        let app = NSApp();
        app.setActivationPolicy_(
            NSApplicationActivationPolicy::NSApplicationActivationPolicyRegular,
        );
    }
}

/// Show and focus the main window (cross-platform)
fn show_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        // For macOS: ensure app is shown and window is visible
        #[cfg(target_os = "macos")]
        {
            set_activation_policy_regular();
            let _ = app.show();
        }

        // Check if window is visible, if not show it
        match window.is_visible() {
            Ok(false) | Err(_) => {
                if let Err(e) = window.show() {
                    eprintln!("Failed to show window: {}", e);
                }
            }
            _ => {}
        }

        // Unminimize if minimized
        match window.is_minimized() {
            Ok(true) => {
                if let Err(e) = window.unminimize() {
                    eprintln!("Failed to unminimize window: {}", e);
                }
            }
            _ => {}
        }

        // Set focus
        if let Err(e) = window.set_focus() {
            eprintln!("Failed to set focus: {}", e);
        }
    }
}

fn main() {
    // Load .sage_env file first before setting other environment variables
    load_sage_env_file();
    
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // 当检测到已有实例运行时，显示原有窗口
            show_window(app);
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(SidecarPid(Mutex::new(None)))
        .manage(Tray(Mutex::new(None)))
        .manage(ClosePreferenceState(Mutex::new(load_close_preference())))
        .on_window_event(|window, event| {
            match event {
                WindowEvent::DragDrop(drag_event) => {
                    // 处理文件拖拽事件
                    match drag_event {
                        tauri::DragDropEvent::Enter { paths, position: _ } => {
                            println!("Drag enter with {} paths", paths.len());
                            // 发射事件给前端
                            let _ = window.emit("tauri-drag-enter", paths.clone());
                        }
                        tauri::DragDropEvent::Drop { paths, position: _ } => {
                            println!("Drop with {} paths", paths.len());
                            // 发射事件给前端
                            let _ = window.emit("tauri-drag-drop", paths.clone());
                        }
                        tauri::DragDropEvent::Leave => {
                            println!("Drag leave");
                            let _ = window.emit("tauri-drag-leave", ());
                        }
                        _ => {}
                    }
                }
                WindowEvent::CloseRequested { api, .. } => {
                    api.prevent_close();
                    
                    let app_handle = window.app_handle().clone();
                    let window = window.clone();
                    
                    tauri::async_runtime::spawn(async move {
                        let state = app_handle.state::<ClosePreferenceState>();
                        let preference = state.0.lock().unwrap().clone();
                        
                        println!("Close requested, preference: {:?}", preference);
                        
                        if let Some(pref) = preference {
                            println!("Found preference: remember_choice={}, action={:?}", pref.remember_choice, pref.action);
                            if pref.remember_choice {
                                match pref.action {
                                    CloseAction::HideToTray => {
                                        #[cfg(target_os = "macos")]
                                        {
                                            set_activation_policy_accessory();
                                            let _ = app_handle.hide();
                                        }
                                        let _ = window.hide();
                                    }
                                    CloseAction::ExitApp => {
                                        if let Some(sidecar_state) = app_handle.try_state::<SidecarPid>() {
                                            let mut pid_guard = sidecar_state.0.lock().unwrap();
                                            if let Some(pid) = *pid_guard {
                                                #[cfg(unix)]
                                                std::process::Command::new("kill")
                                                    .arg(pid.to_string())
                                                    .output()
                                                    .ok();
                                                #[cfg(windows)]
                                                std::process::Command::new("taskkill")
                                                    .args(["/F", "/PID", &pid.to_string()])
                                                    .output()
                                                    .ok();
                                                *pid_guard = None;
                                            }
                                        }
                                        app_handle.exit(0);
                                    }
                                }
                                return;
                            }
                        }
                        
                        // 发射事件给前端，让前端显示自定义关闭对话框
                        let _ = app_handle.emit("show-close-dialog", ());
                    });
                }
                WindowEvent::Destroyed => {
                    // 清理工作已在退出时处理，这里不需要额外操作
                }
                WindowEvent::Focused(focused) => {
                    if *focused {
                        match window.is_visible() {
                            Ok(false) => {
                                let app_handle = window.app_handle();
                                show_window(&app_handle);
                            }
                            _ => {}
                        }
                    }
                }
                _ => {}
            }
        })
        .setup(|app| {
            let show = MenuItemBuilder::with_id("show", "显示").build(app)?;
            let quit = MenuItemBuilder::with_id("quit", "退出").build(app)?;
            let separator = PredefinedMenuItem::separator(app)?;
            let tray_menu = MenuBuilder::new(app)
                .items(&[&show, &separator, &quit])
                .build()?;

            let icon = Image::from_bytes(include_bytes!("../icons/32x32.png")).expect("Failed to load icon");

            let tray = TrayIconBuilder::with_id("main-tray")
                .menu(&tray_menu)
                .icon(icon)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "quit" => {
                        if let Some(state) = app.try_state::<SidecarPid>() {
                            let mut pid_guard = state.0.lock().unwrap();
                            if let Some(pid) = *pid_guard {
                                #[cfg(unix)]
                                std::process::Command::new("kill")
                                    .arg(pid.to_string())
                                    .output()
                                    .ok();
                                #[cfg(windows)]
                                std::process::Command::new("taskkill")
                                    .args(["/F", "/PID", &pid.to_string()])
                                    .output()
                                    .ok();
                                *pid_guard = None;
                            }
                        }
                        app.exit(0);
                    }
                    "show" => {
                        show_window(app);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    match event {
                        TrayIconEvent::Click {
                            button: MouseButton::Left,
                            ..
                        } => {
                            show_window(&tray.app_handle());
                        }
                        TrayIconEvent::DoubleClick {
                            button: MouseButton::Left,
                            ..
                        } => {
                            show_window(&tray.app_handle());
                        }
                        _ => {}
                    }
                })
                .build(app)?;

            if let Some(tray_state) = app.try_state::<Tray>() {
                *tray_state.0.lock().unwrap() = Some(tray);
            }

            let app_handle = app.handle().clone();
            
            // Set default environment variables
            std::env::set_var("SAGE_USE_SANDBOX", "False");

            // Get home directory from environment variable
            let home_dir = std::env::var("HOME")
                .or_else(|_| std::env::var("USERPROFILE"))
                .unwrap_or_default();
            let skill_workspace = format!("{}/.sage/skills", home_dir);
            let session_workspace = format!("{}/.sage/workspace", home_dir);
            std::env::set_var("SAGE_SKILL_WORKSPACE", &skill_workspace);
            std::env::set_var("SAGE_SESSION_DIR", &session_workspace);
            std::env::set_var("SAGE_ROOT", format!("{}/.sage", home_dir));
            println!("Set SAGE_SKILL_WORKSPACE: {}", skill_workspace);

            // Find a free port
            let port = std::net::TcpListener::bind("127.0.0.1:0")
                .map(|l| l.local_addr().unwrap().port())
                .expect("failed to find free port");
            std::env::set_var("SAGE_PORT", port.to_string());
            println!("Set SAGE_PORT: {}", port);
            
            
            tauri::async_runtime::spawn(async move {
                // Determine how to run the backend
                let (command, args) = if cfg!(debug_assertions) {
                    // In debug mode, try to run python directly
                    // We need to find the python script path relative to the project root
                    // The current working directory when running `cargo tauri dev` is typically app/desktop/tauri
                    // So we need to go up to app/desktop/core/main.py or entry.py
                    // Let's assume we are in app/desktop/tauri
                    let mut script_path = std::env::current_dir().unwrap();
                    // If we are in tauri directory, we go up to find entry.py
                    if script_path.ends_with("tauri") {
                        script_path.pop(); // app/desktop
                    } else if script_path.ends_with("src-tauri") {
                        script_path.pop(); // app/desktop (if named src-tauri)
                    }
                    
                    let entry_py = script_path.join("entry.py");
                    
                    if entry_py.exists() {
                        println!("Running python script directly: {:?}", entry_py);
                        // Use environment variable SAGE_PYTHON if set, otherwise try common conda paths
                        let (python_cmd, mut python_args) = if let Ok(sage_python) = std::env::var("SAGE_PYTHON") {
                            println!("Using SAGE_PYTHON: {}", sage_python);
                            (sage_python, vec![])
                        } else {
                            let mut possible_paths: Vec<String> = if cfg!(target_os = "windows") {
                                let user_profile = std::env::var("USERPROFILE").unwrap_or_default();
                                vec![
                                    format!(r"{}\miniconda3\envs\sage-desktop-env\python.exe", user_profile),
                                    format!(r"{}\anaconda3\envs\sage-desktop-env\python.exe", user_profile),
                                    r"C:\ProgramData\miniconda3\envs\sage-desktop-env\python.exe".to_string(),
                                    r"C:\ProgramData\anaconda3\envs\sage-desktop-env\python.exe".to_string(),
                                ]
                            } else {
                                let home_dir = std::env::var("HOME").unwrap_or_default();
                                vec![
                                    format!("{}/.conda/envs/sage-desktop-env/bin/python", home_dir),
                                    format!("{}/opt/anaconda3/envs/sage-desktop-env/bin/python", home_dir),
                                    format!("{}/anaconda3/envs/sage-desktop-env/bin/python", home_dir),
                                    format!("{}/miniconda3/envs/sage-desktop-env/bin/python", home_dir),
                                    "/opt/anaconda3/envs/sage-desktop-env/bin/python".to_string(),
                                    "/opt/miniconda3/envs/sage-desktop-env/bin/python".to_string(),
                                ]
                            };
                            if let Ok(conda_prefix) = std::env::var("CONDA_PREFIX") {
                                if cfg!(target_os = "windows") {
                                    possible_paths.insert(0, format!(r"{}\python.exe", conda_prefix));
                                } else {
                                    possible_paths.insert(0, format!("{}/bin/python", conda_prefix));
                                }
                            }
                            let mut found = None;
                            for path in &possible_paths {
                                if PathBuf::from(path).exists() {
                                    found = Some(path.clone());
                                    break;
                                }
                            }
                            match found {
                                Some(path) => {
                                    println!("Using conda python: {}", path);
                                    (path, vec![])
                                }
                                None => {
                                    if cfg!(target_os = "windows") {
                                        let py_launcher = PathBuf::from(r"C:\Windows\py.exe");
                                        if py_launcher.exists() {
                                            println!("Conda python not found, falling back to py -3");
                                            ("py".to_string(), vec!["-3".to_string()])
                                        } else {
                                            println!("Conda python not found, falling back to python");
                                            ("python".to_string(), vec![])
                                        }
                                    } else {
                                        println!("Conda python not found, falling back to python3");
                                        ("python3".to_string(), vec![])
                                    }
                                }
                            }
                        };
                        python_args.push(entry_py.to_string_lossy().to_string());
                        (python_cmd, python_args)
                    } else {
                        // Fallback to sidecar if script not found
                         println!("Python script not found at {:?}, falling back to sidecar", script_path);
                         // Resolve the sidecar path from resources
                        let sidecar_dir = app_handle
                            .path()
                            .resolve("sidecar", BaseDirectory::Resource)
                            .expect("failed to resolve sidecar resource");
                        
                        let sidecar_executable = if cfg!(target_os = "windows") {
                            sidecar_dir.join("sage-desktop.exe")
                        } else {
                            sidecar_dir.join("sage-desktop")
                        };
                        (sidecar_executable.to_string_lossy().to_string(), vec![])
                    }
                } else {
                     // In release mode, always use sidecar
                    let sidecar_dir = app_handle
                        .path()
                        .resolve("sidecar", BaseDirectory::Resource)
                        .expect("failed to resolve sidecar resource");
                    
                    let sidecar_executable = if cfg!(target_os = "windows") {
                        sidecar_dir.join("sage-desktop.exe")
                    } else {
                        sidecar_dir.join("sage-desktop")
                    };
                    (sidecar_executable.to_string_lossy().to_string(), vec![])
                };

                println!("Spawning backend: {} {:?}", command, args);

                let mut cmd = Command::new(command);
                cmd.args(args)
                    .env("SAGE_PORT", port.to_string())
                    .env("OMP_NUM_THREADS", "4")
                    .env("MKL_NUM_THREADS", "4")
                    .env("TOKENIZERS_PARALLELISM", "false")
                    .env("RAYON_NUM_THREADS", "4")
                    .stdout(Stdio::piped())
                    .stderr(Stdio::piped());

                #[cfg(target_os = "windows")]
                {
                    #[allow(unused_imports)]
                    use std::os::windows::process::CommandExt;
                    const CREATE_NO_WINDOW: u32 = 0x08000000;
                    const BELOW_NORMAL_PRIORITY_CLASS: u32 = 0x00004000;
                    cmd.creation_flags(CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS);
                }

                let mut child = cmd.spawn()
                    .expect("Failed to spawn backend");

                if let Some(id) = child.id() {
                    let state = app_handle.state::<SidecarPid>();
                    *state.0.lock().unwrap() = Some(id);
                    
                    let sidecar_pid = Pid::from_u32(id);
                    tauri::async_runtime::spawn(async move {
                        let mut sys = System::new_all();
                        loop {
                            tokio::time::sleep(tokio::time::Duration::from_secs(10)).await;
                            sys.refresh_all();
                            
                            if let Some(process) = sys.process(sidecar_pid) {
                                let memory_mb = process.memory() / 1024 / 1024;
                                if memory_mb > MAX_MEMORY_MB {
                                    eprintln!("WARNING: Sidecar memory usage exceeded {}MB (current: {}MB)", MAX_MEMORY_MB, memory_mb);
                                }
                            } else {
                                break;
                            }
                        }
                    });
                }
                
                println!("Python sidecar spawned");
                
                let stdout = child.stdout.take().expect("Failed to capture stdout");
                let stderr = child.stderr.take().expect("Failed to capture stderr");

                let app_handle_clone = app_handle.clone();
                tauri::async_runtime::spawn(async move {
                    let mut reader = BufReader::new(stderr).lines();
                    while let Ok(Some(line)) = reader.next_line().await {
                        eprintln!("PYTHON STDERR: {}", line);
                        if line.contains("Permission denied") && line.contains("Full Disk Access") {
                             app_handle_clone.emit("imessage-permission-denied", ()).unwrap();
                        }
                    }
                });

                let mut reader = BufReader::new(stdout).lines();

                // Read events from sidecar
                while let Ok(Some(line)) = reader.next_line().await {
                    let line: String = line;
                    println!("PYTHON: {}", line);
                    if line.contains("Starting Sage Desktop Server on port") {
                        // Extract port. Line format: "Starting Sage Desktop Server on port 12345..."
                        if let Some(last_word) = line.split_whitespace().rev().next() {
                            let clean_port: &str = last_word.trim_matches('.');
                            if let Ok(port) = clean_port.parse::<u16>() {
                                println!("Detected port: {}", port);
                                println!("Emitting sage-desktop-ready event...");
                                // Emit event to frontend
                                app_handle.emit("sage-desktop-ready", Payload { port }).unwrap();
                            }
                        }
                    }
                }
                
                // Wait for child to exit
                let status = child.wait().await;
                println!("Sidecar exited with status: {:?}", status);
                
                eprintln!("Sidecar process exited, application will need to be restarted");
                app_handle.emit("sage-sidecar-exited", ()).ok();
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_server_port, get_system_proxy, get_sage_env_content, save_sage_env_content, handle_close_dialog_result])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
