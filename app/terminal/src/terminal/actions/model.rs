use anyhow::Result;

use crate::app::{App, MessageKind};
use crate::backend::{init_config as init_config_api, read_config, read_doctor_info};
use crate::terminal_support::{format_config, format_config_init, format_doctor_info};

pub(super) fn show_config(app: &mut App) -> Result<bool> {
    match read_config() {
        Ok(config) => {
            app.push_message(
                MessageKind::Tool,
                format_config(&config, &app.selected_model),
            );
            app.set_status(format!("config  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(MessageKind::System, format!("failed to read config: {err}"));
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn show_doctor(app: &mut App, probe_provider: bool) -> Result<bool> {
    match read_doctor_info(probe_provider) {
        Ok(info) => {
            app.push_message(MessageKind::Tool, format_doctor_info(&info));
            app.set_status(format!("doctor  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(
                MessageKind::System,
                format!("failed to read doctor info: {err}"),
            );
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn init_config(app: &mut App, path: Option<&str>, force: bool) -> Result<bool> {
    match init_config_api(path, force) {
        Ok(result) => {
            app.push_message(MessageKind::Tool, format_config_init(&result));
            app.set_status(format!("config  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(
                MessageKind::System,
                format!("failed to initialize config: {err}"),
            );
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn show_model(app: &mut App) -> Result<bool> {
    match read_config() {
        Ok(config) => {
            let effective = app
                .selected_model
                .clone()
                .unwrap_or_else(|| config.default_model_name.clone());
            let source = if app.selected_model.is_some() {
                "session override"
            } else {
                "CLI default"
            };
            app.push_message(
                MessageKind::Tool,
                format!(
                    "current model: {}\nsource: {}\ndefault model: {}",
                    effective, source, config.default_model_name
                ),
            );
            app.set_status(format!("model  {}", app.session_id));
        }
        Err(err) => {
            app.push_message(MessageKind::System, format!("failed to read config: {err}"));
            app.set_status(format!("error  {}", app.session_id));
        }
    }
    Ok(true)
}

pub(super) fn set_model(app: &mut App, model: String) -> Result<bool> {
    app.set_model_override(model);
    Ok(true)
}

pub(super) fn clear_model(app: &mut App) -> Result<bool> {
    app.clear_model_override();
    Ok(true)
}
