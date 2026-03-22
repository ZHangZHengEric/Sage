#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

#[cfg(target_os = "macos")]
use cocoa::appkit::{NSApp, NSApplication, NSApplicationActivationPolicy};
use serde::{Deserialize, Serialize};
use std::ffi::OsString;
use std::path::Path;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Mutex;
use sysinfo::{Pid, System};
use tauri::{
    image::Image,
    menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem},
    path::BaseDirectory,
    tray::{MouseButton, TrayIcon, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, WindowEvent,
};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

const MAX_MEMORY_MB: u64 = 2048;

struct SidecarPid(Mutex<Option<u32>>);
struct Tray(Mutex<Option<TrayIcon>>);

#[derive(Debug, Clone)]
struct NodeRuntime {
    node_executable: PathBuf,
    npm_cli: Option<PathBuf>,
    bin_dir: PathBuf,
}

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
const SAGE_NODE_MODULES_DIR: &str = ".sage_node_env";

#[cfg(target_os = "linux")]
fn apply_linux_webkit_env_defaults() {
    // Work around white screen issues on some Linux GPU/WebKitGTK setups.
    // Respect user overrides if they already set these env vars.
    if std::env::var_os("WEBKIT_DISABLE_COMPOSITING_MODE").is_none() {
        std::env::set_var("WEBKIT_DISABLE_COMPOSITING_MODE", "1");
    }
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
}

#[cfg(not(target_os = "linux"))]
fn apply_linux_webkit_env_defaults() {}

// 预设的 npx 包列表
const PRESET_NPX_PACKAGES: &[&str] = &[
    // Skill 依赖
    "agent-browser", // social-push, agent-browser skills
    "docx",          // docx skill - 创建 Word 文档
];

fn get_sage_root_dir() -> PathBuf {
    let home_dir = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_default();
    PathBuf::from(home_dir).join(".sage")
}

fn get_sage_node_modules_dir() -> PathBuf {
    get_sage_root_dir().join(SAGE_NODE_MODULES_DIR)
}

fn first_existing_path(candidates: impl IntoIterator<Item = PathBuf>) -> Option<PathBuf> {
    candidates.into_iter().find(|path| path.exists())
}

fn build_prepended_path(path: &Path, current_path: Option<OsString>) -> Result<OsString, String> {
    let mut paths = vec![path.to_path_buf()];
    if let Some(current_path) = current_path {
        paths.extend(std::env::split_paths(&current_path));
    }

    std::env::join_paths(paths)
        .map_err(|e| format!("Failed to construct PATH with bundled Node runtime: {}", e))
}

fn resolve_bundled_node_runtime(app_handle: &tauri::AppHandle) -> Option<NodeRuntime> {
    let node_dir = app_handle
        .path()
        .resolve("sidecar/node", BaseDirectory::Resource)
        .ok()
        .filter(|path| path.exists())
        .or_else(|| {
            app_handle
                .path()
                .resolve("node", BaseDirectory::Resource)
                .ok()
                .filter(|path| path.exists())
        })?;

    let node_executable = first_existing_path([
        node_dir.join("node"),
        node_dir.join("node.exe"),
        node_dir.join("bin").join("node"),
        node_dir.join("bin").join("node.exe"),
    ])?;

    let npm_cli = first_existing_path([
        node_dir
            .join("lib")
            .join("node_modules")
            .join("npm")
            .join("bin")
            .join("npm-cli.js"),
        node_dir
            .join("node_modules")
            .join("npm")
            .join("bin")
            .join("npm-cli.js"),
    ]);

    let bin_dir = node_executable
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| node_dir.clone());

    Some(NodeRuntime {
        node_executable,
        npm_cli,
        bin_dir,
    })
}

fn apply_bundled_node_runtime(runtime: &NodeRuntime) -> Result<(), String> {
    let path_with_node = build_prepended_path(&runtime.bin_dir, std::env::var_os("PATH"))?;
    std::env::set_var("PATH", &path_with_node);
    std::env::set_var(
        "SAGE_NODE_EXECUTABLE",
        runtime.node_executable.to_string_lossy().to_string(),
    );
    if let Some(npm_cli) = &runtime.npm_cli {
        std::env::set_var("SAGE_NPM_CLI", npm_cli.to_string_lossy().to_string());
    }
    println!(
        "Using bundled Node runtime at {:?}",
        runtime.node_executable
    );
    Ok(())
}

fn configure_sage_node_environment() -> PathBuf {
    let node_modules_dir = get_sage_node_modules_dir();
    let node_modules_path = node_modules_dir.to_string_lossy().to_string();
    let node_modules_lib = node_modules_dir.join("node_modules");
    let node_path = node_modules_lib.to_string_lossy().to_string();

    std::env::set_var("SAGE_NODE_MODULES_DIR", &node_modules_path);
    std::env::set_var("SAGE_NODE_PATH", &node_path);
    std::env::set_var("NODE_PATH", &node_path);

    println!("Prepared SAGE_NODE_MODULES_DIR: {}", node_modules_path);
    println!("Prepared SAGE_NODE_PATH: {}", node_path);

    node_modules_dir
}

fn build_npm_command(node_runtime: Option<&NodeRuntime>) -> Result<Command, String> {
    let mut cmd = if let Some(runtime) = node_runtime {
        if let Some(npm_cli) = &runtime.npm_cli {
            let mut cmd = Command::new(&runtime.node_executable);
            cmd.arg(npm_cli);
            cmd
        } else {
            eprintln!(
                "Bundled Node runtime found at {:?}, but npm-cli.js is missing. Falling back to system npm.",
                runtime.node_executable
            );
            Command::new("npm")
        }
    } else {
        Command::new("npm")
    };

    if let Some(runtime) = node_runtime {
        let path_with_node = build_prepended_path(&runtime.bin_dir, std::env::var_os("PATH"))?;
        cmd.env("PATH", path_with_node);
    }

    Ok(cmd)
}

/// 检查用户是否选择跳过 npx 包安装
fn should_skip_npx_install() -> bool {
    let skip_flag_file = get_sage_root_dir().join(".skip_npx_install");
    skip_flag_file.exists()
}

/// 创建跳过安装的标记文件
fn create_skip_npx_install_flag() -> Result<(), String> {
    let skip_flag_file = get_sage_root_dir().join(".skip_npx_install");
    std::fs::write(&skip_flag_file, "")
        .map_err(|e| format!("Failed to create skip flag file: {}", e))
}

/// 初始化 .sage_node_modules 目录并安装预设的 npx 包
async fn initialize_sage_node_modules(
    node_runtime: Option<NodeRuntime>,
    app_handle: &tauri::AppHandle,
) -> Result<PathBuf, String> {
    let sage_root = get_sage_root_dir();
    let node_modules_dir = sage_root.join(SAGE_NODE_MODULES_DIR);

    // 检查用户是否选择跳过安装
    if should_skip_npx_install() {
        println!("User chose to skip npx package installation");
        let _ = app_handle.emit("sage-npx-install-skipped", ());
        return Ok(node_modules_dir);
    }

    // 创建目录
    if !node_modules_dir.exists() {
        println!(
            "Creating .sage_node_modules directory at {:?}",
            node_modules_dir
        );
        std::fs::create_dir_all(&node_modules_dir)
            .map_err(|e| format!("Failed to create .sage_node_modules directory: {}", e))?;
    }

    // 检查是否需要初始化 npm
    let package_json_path = node_modules_dir.join("package.json");
    if !package_json_path.exists() {
        println!("Initializing npm in .sage_node_modules...");

        // 手动创建 package.json，因为目录名以点开头，npm init 会报错
        let package_json_content = serde_json::json!({
            "name": "sage-node-modules",
            "version": "1.0.0",
            "description": "Sage npx packages environment",
            "private": true
        });

        std::fs::write(&package_json_path, package_json_content.to_string())
            .map_err(|e| format!("Failed to create package.json: {}", e))?;

        // 创建 .npmrc 文件配置国内镜像源
        let npmrc_path = node_modules_dir.join(".npmrc");
        let npmrc_content = r#"registry=https://registry.npmmirror.com
@anthropics:registry=https://registry.npmmirror.com
@modelcontextprotocol:registry=https://registry.npmmirror.com
"#;
        std::fs::write(&npmrc_path, npmrc_content)
            .map_err(|e| format!("Failed to create .npmrc: {}", e))?;

        println!("package.json and .npmrc created successfully");
    }

    // 安装预设的 npx 包
    println!("Installing preset npx packages...");
    
    // 发送开始安装事件
    let total_packages = PRESET_NPX_PACKAGES.len();
    let _ = app_handle.emit("sage-npx-install-started", serde_json::json!({
        "total": total_packages,
        "packages": PRESET_NPX_PACKAGES,
    }));
    
    if let Some(runtime) = node_runtime.as_ref() {
        println!("Using Node.js: {:?}", runtime.node_executable);
        println!("Using NPM CLI: {:?}", runtime.npm_cli);
    } else {
        println!("Using system npm to install preset npx packages");
    }
    
    let mut installed_count = 0;
    let mut failed_packages: Vec<String> = Vec::new();
    
    for (index, package) in PRESET_NPX_PACKAGES.iter().enumerate() {
        let package_name = *package;
        println!("Checking package: {}", package_name);

        // 发送进度事件
        let _ = app_handle.emit("sage-npx-install-progress", serde_json::json!({
            "current": index + 1,
            "total": total_packages,
            "package": package_name,
            "status": "checking",
        }));

        // 检查包是否已安装 (对于 scoped packages，检查 scope 目录)
        let scoped_package_dir = node_modules_dir
            .join("node_modules")
            .join(package_name.split('/').next().unwrap_or(""));

        if scoped_package_dir.exists() {
            println!("Package {} already installed, skipping", package_name);
            installed_count += 1;
            let _ = app_handle.emit("sage-npx-install-progress", serde_json::json!({
                "current": index + 1,
                "total": total_packages,
                "package": package_name,
                "status": "skipped",
            }));
            continue;
        }

        println!("Installing package: {}", package_name);
        
        // 发送开始安装事件
        let _ = app_handle.emit("sage-npx-install-progress", serde_json::json!({
            "current": index + 1,
            "total": total_packages,
            "package": package_name,
            "status": "installing",
        }));

        let mut install_command = build_npm_command(node_runtime.as_ref())?;
        let install_result = install_command
            .args(["install", package_name, "--save"])
            .current_dir(&node_modules_dir)
            .output()
            .await
            .map_err(|e| format!("Failed to install package {}: {}", package_name, e))?;

        if install_result.status.success() {
            println!("Successfully installed {}", package_name);
            installed_count += 1;
            let _ = app_handle.emit("sage-npx-install-progress", serde_json::json!({
                "current": index + 1,
                "total": total_packages,
                "package": package_name,
                "status": "success",
            }));
        } else {
            let stderr = String::from_utf8_lossy(&install_result.stderr);
            eprintln!("Warning: Failed to install {}: {}", package_name, stderr);
            failed_packages.push(package_name.to_string());
            let _ = app_handle.emit("sage-npx-install-progress", serde_json::json!({
                "current": index + 1,
                "total": total_packages,
                "package": package_name,
                "status": "failed",
                "error": stderr.to_string(),
            }));
            // 继续安装其他包，不中断
        }
    }

    println!("Preset npx packages installation completed");
    
    // 发送完成事件
    let _ = app_handle.emit("sage-npx-install-completed", serde_json::json!({
        "total": total_packages,
        "installed": installed_count,
        "failed": failed_packages,
    }));
    
    Ok(node_modules_dir)
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
fn get_sage_node_modules_path() -> Result<String, String> {
    match std::env::var("SAGE_NODE_MODULES_DIR") {
        Ok(path) => Ok(path),
        Err(_) => {
            // 如果环境变量未设置，尝试获取默认路径
            let default_path = get_sage_node_modules_dir();
            if default_path.exists() {
                Ok(default_path.to_string_lossy().to_string())
            } else {
                Err("SAGE_NODE_MODULES_DIR not initialized yet".to_string())
            }
        }
    }
}

#[tauri::command]
fn get_sage_node_path() -> Option<String> {
    std::env::var("SAGE_NODE_PATH").ok()
}

#[tauri::command]
fn skip_npx_installation() -> Result<(), String> {
    println!("User requested to skip npx package installation");
    create_skip_npx_install_flag()
}

#[tauri::command]
fn is_npx_installation_skipped() -> bool {
    should_skip_npx_install()
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

// #[tauri::command(async)]
// fn get_system_proxy() -> Option<String> {
//     // 1. Try environment variables first
//     if let Ok(proxy) = std::env::var("HTTP_PROXY")
//         .or_else(|_| std::env::var("http_proxy"))
//         .or_else(|_| std::env::var("HTTPS_PROXY"))
//         .or_else(|_| std::env::var("https_proxy"))
//         .or_else(|_| std::env::var("ALL_PROXY"))
//         .or_else(|_| std::env::var("all_proxy"))
//     {
//         return Some(proxy);
//     }

//     // 2. macOS specific check using scutil
//     #[cfg(target_os = "macos")]
//     {
//         use std::process::Command;
//         if let Ok(output) = Command::new("scutil").arg("--proxy").output() {
//             let output_str = String::from_utf8_lossy(&output.stdout);

//             let mut host = String::new();
//             let mut port = String::new();
//             let mut enabled = false;

//             for line in output_str.lines() {
//                 let line = line.trim();
//                 if line.starts_with("HTTPEnable") && line.contains("1") {
//                     enabled = true;
//                 }
//                 if line.starts_with("HTTPProxy") {
//                     if let Some(val) = line.split(':').nth(1) {
//                         host = val.trim().to_string();
//                     }
//                 }
//                 if line.starts_with("HTTPPort") {
//                      if let Some(val) = line.split(':').nth(1) {
//                         port = val.trim().to_string();
//                     }
//                 }
//             }

//             if enabled && !host.is_empty() && !port.is_empty() {
//                 return Some(format!("http://{}:{}", host, port));
//             }
//         }
//     }

//     // 3. Windows specific check using netsh
//     #[cfg(target_os = "windows")]
//     {
//         use std::process::Command;
//         if let Ok(output) = Command::new("netsh").args(["winhttp", "show", "proxy"]).output() {
//             let output_str = String::from_utf8_lossy(&output.stdout);
//             // Check if proxy is enabled (not "Direct access")
//             if !output_str.contains("Direct access") {
//                 // Try to extract proxy server address
//                 for line in output_str.lines() {
//                     let line = line.trim();
//                     if line.starts_with("Proxy Server(s)") || line.starts_with("Proxy Server") {
//                         if let Some(proxy_part) = line.split(':').nth(1) {
//                             let proxy = proxy_part.trim().to_string();
//                             if !proxy.is_empty() {
//                                 // Add http:// prefix if not present
//                                 if !proxy.starts_with("http://") && !proxy.starts_with("https://") {
//                                     return Some(format!("http://{}", proxy));
//                                 }
//                                 return Some(proxy);
//                             }
//                         }
//                     }
//                 }
//             }
//         }
//     }

//     None
// }

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
    apply_linux_webkit_env_defaults();

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
                WindowEvent::Resized(_) => {
                    // 窗口大小改变时，通知前端刷新
                    let _ = window.emit("tauri-window-resized", ());
                }
                WindowEvent::ScaleFactorChanged { .. } => {
                    // DPI 缩放改变时，通知前端刷新
                    let _ = window.emit("tauri-scale-factor-changed", ());
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

            let bundled_node_runtime = resolve_bundled_node_runtime(&app_handle);
            if let Some(runtime) = bundled_node_runtime.as_ref() {
                if let Err(e) = apply_bundled_node_runtime(runtime) {
                    eprintln!("Failed to prepare bundled Node runtime: {}", e);
                }
            } else {
                println!("Bundled Node runtime not found, falling back to system Node/npm");
            }

            configure_sage_node_environment();

            // Initialize .sage_node_modules and set environment variable
            let app_handle_clone = app.handle().clone();
            let node_runtime_for_init = bundled_node_runtime.clone();
            let bundled_node_path = bundled_node_runtime
                .as_ref()
                .map(|runtime| runtime.bin_dir.to_string_lossy().to_string());
            tauri::async_runtime::spawn(async move {
                match initialize_sage_node_modules(node_runtime_for_init, &app_handle_clone).await {
                    Ok(node_modules_dir) => {
                        let node_modules_path = node_modules_dir.to_string_lossy().to_string();
                        std::env::set_var("SAGE_NODE_MODULES_DIR", &node_modules_path);
                        println!("Set SAGE_NODE_MODULES_DIR: {}", node_modules_path);

                        // Also set NODE_PATH to include the node_modules
                        let node_modules_lib = node_modules_dir.join("node_modules");
                        let node_path = node_modules_lib.to_string_lossy().to_string();
                        std::env::set_var("SAGE_NODE_PATH", &node_path);
                        std::env::set_var("NODE_PATH", &node_path);
                        println!("Set SAGE_NODE_PATH: {}", node_path);

                        // Emit event to notify frontend that node_modules is ready
                        let _ = app_handle_clone.emit("sage-node-modules-ready", node_modules_path);
                    }
                    Err(e) => {
                        eprintln!("Failed to initialize .sage_node_modules: {}", e);
                    }
                }
            });

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
                
                // Pass bundled Node.js path to Python backend
                if let Some(ref node_bin) = bundled_node_path {
                    cmd.env("SAGE_BUNDLED_NODE_BIN", node_bin);
                }

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
                let mut backend_started = false;
                let start_time = std::time::Instant::now();
                let timeout = std::time::Duration::from_secs(60); // 60秒超时

                // Read events from sidecar with timeout
                while let Ok(Some(line)) = reader.next_line().await {
                    let line: String = line;
                    println!("PYTHON: {}", line);
                    
                    // Check for startup timeout
                    if !backend_started && start_time.elapsed() > timeout {
                        eprintln!("Backend startup timeout after 60 seconds");
                        app_handle.emit("sage-backend-startup-failed", serde_json::json!({
                            "reason": "timeout",
                            "message": "后端服务启动超时，请检查应用是否完整安装"
                        })).unwrap();
                        break;
                    }
                    
                    if line.contains("Starting Sage Desktop Server on port") {
                        // Extract port. Line format: "Starting Sage Desktop Server on port 12345..."
                        if let Some(last_word) = line.split_whitespace().rev().next() {
                            let clean_port: &str = last_word.trim_matches('.');
                            if let Ok(port) = clean_port.parse::<u16>() {
                                println!("Detected port: {}", port);
                                println!("Emitting sage-desktop-ready event...");
                                backend_started = true;
                                // Emit event to frontend
                                app_handle.emit("sage-desktop-ready", Payload { port }).unwrap();
                            }
                        }
                    } else if line.contains("Error:") || line.contains("Traceback") {
                        // Backend reported an error during startup
                        if !backend_started {
                            eprintln!("Backend startup error detected: {}", line);
                            app_handle.emit("sage-backend-startup-failed", serde_json::json!({
                                "reason": "error",
                                "message": format!("后端启动错误: {}", line)
                            })).unwrap();
                        }
                    }
                }

                // If backend never started and we exited the loop, notify frontend
                if !backend_started {
                    eprintln!("Backend process exited without starting successfully");
                    app_handle.emit("sage-backend-startup-failed", serde_json::json!({
                        "reason": "crashed",
                        "message": "后端进程异常退出，请检查日志或尝试重启应用"
                    })).unwrap();
                }

                // Wait for child to exit
                let status = child.wait().await;
                println!("Sidecar exited with status: {:?}", status);

                eprintln!("Sidecar process exited, application will need to be restarted");
                app_handle.emit("sage-sidecar-exited", ()).ok();
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_server_port, get_sage_env_content, save_sage_env_content, handle_close_dialog_result, get_sage_node_modules_path, get_sage_node_path, skip_npx_installation, is_npx_installation_skipped])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
