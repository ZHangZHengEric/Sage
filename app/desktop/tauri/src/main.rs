#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use tauri::{
    api::process::{Command, CommandEvent},
    // CustomMenuItem, Manager, SystemTray, SystemTrayEvent, SystemTrayMenu, SystemTrayMenuItem,
    Manager,
};

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
            
            tauri::async_runtime::spawn(async move {
                let (mut rx, _child) = Command::new_sidecar("sage-desktop-sidecar")
                    .expect("failed to create `sage-desktop-sidecar` binary command")
                    .spawn()
                    .expect("Failed to spawn sidecar");
                
                println!("Python sidecar spawned");
                
                // Read events from sidecar
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("PYTHON: {}", line);
                            if line.contains("Starting Sage Desktop Server on port") {
                                // Extract port. Line format: "Starting Sage Desktop Server on port 12345..."
                                if let Some(last_word) = line.split_whitespace().rev().next() {
                                    let clean_port = last_word.trim_matches('.');
                                    if let Ok(port) = clean_port.parse::<u16>() {
                                        println!("Detected port: {}", port);
                                        // Emit event to frontend
                                        app_handle.emit_all("sage-desktop-ready", Payload { port }).unwrap();
                                    }
                                }
                            }
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("PYTHON ERR: {}", line);
                        }
                        _ => {}
                    }
                }
                println!("Python sidecar terminated");
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
