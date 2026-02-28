#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use tauri::{
    // api::process::{Command, CommandEvent},
    // CustomMenuItem, Manager, SystemTray, SystemTrayEvent, SystemTrayMenu, SystemTrayMenuItem,
    Manager, WindowEvent,
};
use tokio::process::Command;
use tokio::io::{BufReader, AsyncBufReadExt};
use std::process::Stdio;
use std::sync::Mutex;

struct SidecarPid(Mutex<Option<u32>>);

#[derive(Clone, serde::Serialize)]
struct Payload {
    port: u16,
}

fn main() {
    /*
    // Tray setup
    let quit = CustomMenuItem::new("quit".to_string(), "Quit");
    let hide = CustomMenuItem::new("hide".to_string(), "Hide");
    let tray_menu = SystemTrayMenu::new()
        .add_item(hide)
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(quit);
    let system_tray = SystemTray::new().with_menu(tray_menu);
    */

    tauri::Builder::default()
        .manage(SidecarPid(Mutex::new(None)))
        .on_window_event(|event| match event.event() {
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
            _ => {}
        })
        /*
        .system_tray(system_tray)
        .on_system_tray_event(|app, event| match event {
            SystemTrayEvent::LeftClick {
                position: _,
                size: _,
                ..
            } => {
                let _window = app.get_window("main").unwrap();
                window.show().unwrap();
                window.set_focus().unwrap();
            }
            SystemTrayEvent::MenuItemClick { id, .. } => match id.as_str() {
                "quit" => {
                    std::process::exit(0);
                }
                "hide" => {
                    let window = app.get_window("main").unwrap();
                    window.hide().unwrap();
                }
                _ => {}
            },
            _ => {}
        })
        */
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
            
            
            tauri::async_runtime::spawn(async move {
                // Resolve the sidecar path from resources
                let sidecar_dir = app_handle.path_resolver()
                    .resolve_resource("sidecar")
                    .expect("failed to resolve sidecar resource");
                
                let sidecar_executable = if cfg!(target_os = "windows") {
                    sidecar_dir.join("sage-desktop.exe")
                } else {
                    sidecar_dir.join("sage-desktop")
                };
                
                println!("Spawning sidecar from: {:?}", sidecar_executable);

                let mut child = Command::new(sidecar_executable)
                    .stdout(Stdio::piped())
                    .stderr(Stdio::piped())
                    .spawn()
                    .expect("Failed to spawn sidecar");

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
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
