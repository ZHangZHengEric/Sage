use crate::app::{App, MessageKind};
use crate::preferences::persist_app_preferences_notice;

const VALID_SANDBOX_TYPES: &[&str] = &["local", "remote", "passthrough"];

impl App {
    pub fn set_sandbox_type_selection(&mut self, sandbox_type: String) {
        self.sandbox_type = Some(sandbox_type.clone());
        self.backend_restart_requested = true;
        persist_app_preferences_notice(self);
        self.queue_message(
            MessageKind::System,
            format!("sandbox type set: {sandbox_type}"),
        );
        self.status = format!("sandbox  {}", self.session_id);
    }

    pub fn clear_sandbox_type_selection(&mut self) {
        match self.sandbox_type.take() {
            Some(sandbox_type) => {
                self.backend_restart_requested = true;
                persist_app_preferences_notice(self);
                self.queue_message(
                    MessageKind::System,
                    format!("cleared sandbox type override: {sandbox_type}"),
                );
            }
            None => {
                self.queue_message(MessageKind::System, "no sandbox type override is active");
            }
        }
        self.status = format!("sandbox  {}", self.session_id);
    }

    pub fn queue_sandbox_status(&mut self) {
        self.queue_message(
            MessageKind::System,
            format!("sandbox: {}", self.sandbox_type_status_label()),
        );
        self.status = format!("sandbox  {}", self.session_id);
    }

    pub(crate) fn sandbox_type_status_label(&self) -> String {
        self.sandbox_type
            .clone()
            .unwrap_or_else(|| "runtime default".to_string())
    }
}

pub(crate) fn normalize_sandbox_type(value: &str) -> Option<String> {
    let normalized = value.trim().to_lowercase();
    if VALID_SANDBOX_TYPES.contains(&normalized.as_str()) {
        Some(normalized)
    } else {
        None
    }
}
