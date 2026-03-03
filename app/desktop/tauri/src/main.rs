#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use tauri::{
    CustomMenuItem, Manager, SystemTray, SystemTrayEvent, SystemTrayMenu, SystemTrayMenuItem,
    WindowEvent,
};
#[cfg(target_os = "macos")]
use cocoa::appkit::{NSApp, NSApplication, NSApplicationActivationPolicy};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Mutex;

struct SidecarPid(Mutex<Option<u32>>);

#[derive(Clone, serde::Serialize)]
struct Payload {
    port: u16,
}

#[tauri::command]
fn get_server_port() -> Option<u16> {
    std::env::var("SAGE_PORT").ok().and_then(|p| p.parse().ok())
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
    if let Some(window) = app.get_window("main") {
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
    // Tray setup
    let show = CustomMenuItem::new("show".to_string(), "显示");
    let quit = CustomMenuItem::new("quit".to_string(), "退出");
    let tray_menu = SystemTrayMenu::new()
        .add_item(show)
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(quit);
    
    let system_tray = SystemTray::new()
        .with_menu(tray_menu);

    tauri::Builder::default()
        .manage(SidecarPid(Mutex::new(None)))
        .on_window_event(|event| {
            match event.event() {
                WindowEvent::CloseRequested { api, .. } => {
                    #[cfg(target_os = "macos")]
                    {
                        set_activation_policy_accessory();
                        let _ = event.window().app_handle().hide();
                    }
                    event.window().hide().unwrap();
                    api.prevent_close();
                }
                WindowEvent::Destroyed => {
                    // When the main window is destroyed (closed), exit the app.
                    // Use app_handle.exit(0) to ensure proper cleanup of child processes.
                    let app_handle = event.window().app_handle();
                    if let Some(state) = app_handle.try_state::<SidecarPid>() {
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
                    event.window().app_handle().exit(0);
                }
                WindowEvent::Focused(focused) => {
                    // When window is focused (e.g., user clicks on Dock icon on macOS)
                    // Only handle if window is currently hidden and being brought to front
                    if *focused {
                        let window = event.window();
                        match window.is_visible() {
                            Ok(false) => {
                                // Window was hidden, now being shown via Dock click
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
        .system_tray(system_tray)
        .on_system_tray_event(|app, event| match event {
            SystemTrayEvent::LeftClick {
                position: _,
                size: _,
                ..
            } => {
                show_window(app);
            }
            SystemTrayEvent::MenuItemClick { id, .. } => match id.as_str() {
                "quit" => {
                    // Kill the sidecar process before exiting
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
                    std::process::exit(0);
                }
                "show" => {
                    show_window(app);
                }
                _ => {}
            },
            _ => {}
        })
        .setup(|app| {
            let _window = app.get_window("main").unwrap();
            let app_handle = app.handle();
            
            // Set default environment variables
            std::env::set_var("SAGE_USE_SANDBOX", "False");

            // Get home directory from environment variable
            let home_dir = std::env::var("HOME")
                .or_else(|_| std::env::var("USERPROFILE"))
                .unwrap_or_default();
            let skill_workspace = format!("{}/.sage/skills", home_dir);
            let session_workspace = format!("{}/.sage/workspace", home_dir);
            std::env::set_var("SAGE_SKILL_WORKSPACE", &skill_workspace);
            std::env::set_var("SAGE_WORKSPACE_PATH", &session_workspace);
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
                        let python_cmd = if let Ok(sage_python) = std::env::var("SAGE_PYTHON") {
                            println!("Using SAGE_PYTHON: {}", sage_python);
                            sage_python
                        } else {
                            // Try common conda paths for sage-desktop-env
                            let home_dir = std::env::var("HOME").unwrap_or_default();
                            let possible_paths = [
                                format!("{}/.conda/envs/sage-desktop-env/bin/python", home_dir),
                                format!("{}/opt/anaconda3/envs/sage-desktop-env/bin/python", home_dir),
                                format!("{}/anaconda3/envs/sage-desktop-env/bin/python", home_dir),
                                format!("{}/miniconda3/envs/sage-desktop-env/bin/python", home_dir),
                                format!("/opt/anaconda3/envs/sage-desktop-env/bin/python"),
                                format!("/opt/miniconda3/envs/sage-desktop-env/bin/python"),
                            ];
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
                                    path
                                }
                                None => {
                                    println!("Conda python not found, falling back to python3");
                                    "python3".to_string()
                                }
                            }
                        };
                        (python_cmd, vec![entry_py.to_string_lossy().to_string()])
                    } else {
                        // Fallback to sidecar if script not found
                         println!("Python script not found at {:?}, falling back to sidecar", script_path);
                         // Resolve the sidecar path from resources
                        let sidecar_dir = app_handle.path_resolver()
                            .resolve_resource("sidecar")
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
                    let sidecar_dir = app_handle.path_resolver()
                        .resolve_resource("sidecar")
                        .expect("failed to resolve sidecar resource");
                    
                    let sidecar_executable = if cfg!(target_os = "windows") {
                        sidecar_dir.join("sage-desktop.exe")
                    } else {
                        sidecar_dir.join("sage-desktop")
                    };
                    (sidecar_executable.to_string_lossy().to_string(), vec![])
                };

                println!("Spawning backend: {} {:?}", command, args);

                let mut child = Command::new(command)
                    .args(args)
                    .env("SAGE_PORT", port.to_string())
                    .stdout(Stdio::piped())
                    .stderr(Stdio::inherit())
                    .spawn()
                    .expect("Failed to spawn backend");

                if let Some(id) = child.id() {
                    let state = app_handle.state::<SidecarPid>();
                    *state.0.lock().unwrap() = Some(id);
                }
                
                println!("Python sidecar spawned");
                
                let stdout = child.stdout.take().expect("Failed to capture stdout");
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
                                app_handle.emit_all("sage-desktop-ready", Payload { port }).unwrap();
                            }
                        }
                    }
                }
                
                // Wait for child to exit
                let status = child.wait().await;
                println!("Sidecar exited with status: {:?}", status);
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_server_port])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
