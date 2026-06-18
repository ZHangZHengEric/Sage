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
        self.queue_message(MessageKind::System, self.sandbox_status_message());
        self.status = format!("sandbox  {}", self.session_id);
    }

    pub(crate) fn sandbox_type_status_label(&self) -> String {
        self.sandbox_type
            .clone()
            .unwrap_or_else(|| "runtime default".to_string())
    }

    pub(crate) fn sandbox_status_message(&self) -> String {
        let profile = sandbox_profile(self.sandbox_type.as_deref());
        let source = if self.sandbox_type.is_some() {
            "session override"
        } else {
            "runtime default"
        };
        let restart = if self.backend_restart_requested {
            "pending; next task will restart backend"
        } else {
            "not pending"
        };
        let workspace = self.workspace_label.clone();
        [
            format!("sandbox: {} ({source})", profile.label),
            format!("workspace: {workspace}"),
            format!("restart: {restart}"),
            format!("filesystem: {}", profile.filesystem),
            format!("commands: {}", profile.commands),
            format!("network: {}", profile.network),
            format!("next: {}", profile.next_step),
        ]
        .join("\n")
    }
}

pub(crate) struct SandboxProfile {
    pub(crate) label: &'static str,
    pub(crate) filesystem: &'static str,
    pub(crate) commands: &'static str,
    pub(crate) network: &'static str,
    pub(crate) next_step: &'static str,
}

pub(crate) fn sandbox_profile(value: Option<&str>) -> SandboxProfile {
    match value {
        Some("local") => SandboxProfile {
            label: "local",
            filesystem: "workspace-backed local sandbox with path permission checks",
            commands: "run through the local sandbox provider",
            network: "inherits local runtime policy",
            next_step: "use /workspace set <path> before coding tasks that need repo files",
        },
        Some("remote") => SandboxProfile {
            label: "remote",
            filesystem: "remote workspace, defaulting to /sage-workspace when unspecified",
            commands: "run in the remote sandbox service when configured",
            network: "depends on the remote sandbox provider",
            next_step: "run /doctor if startup fails or remote credentials are missing",
        },
        Some("passthrough") => SandboxProfile {
            label: "passthrough",
            filesystem: "direct backend workspace access without a stronger isolation boundary",
            commands: "run through the passthrough provider",
            network: "inherits host/runtime access",
            next_step: "use only for trusted workspaces, or switch back with /sandbox set local",
        },
        _ => SandboxProfile {
            label: "runtime default",
            filesystem: "backend resolves the default sandbox mode, usually local",
            commands: "run with backend defaults until /sandbox set overrides them",
            network: "inherits the resolved backend provider policy",
            next_step: "use /sandbox set local|remote|passthrough to make the mode explicit",
        },
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
