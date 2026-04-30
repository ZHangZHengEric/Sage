use crate::app::{App, MessageKind};

const VALID_AGENT_MODES: &[&str] = &["simple", "multi", "fibre"];

impl App {
    pub fn apply_startup_agent_options(
        &mut self,
        agent_id: Option<String>,
        agent_mode: Option<String>,
    ) {
        self.selected_agent_id = agent_id.filter(|value| !value.trim().is_empty());
        if let Some(mode) = agent_mode {
            self.agent_mode = mode;
        }
    }

    pub fn set_selected_agent_id(&mut self, agent_id: String) {
        let normalized = agent_id.trim().to_string();
        self.selected_agent_id = Some(normalized.clone());
        self.clear_agent_catalog();
        self.skill_catalog = None;
        self.backend_restart_requested = true;
        self.queue_message(MessageKind::Tool, format!("agent set: {normalized}"));
        self.status = format!("agent  {}", self.session_id);
    }

    pub fn clear_selected_agent_id(&mut self) {
        match self.selected_agent_id.take() {
            Some(agent_id) => {
                self.clear_agent_catalog();
                self.skill_catalog = None;
                self.backend_restart_requested = true;
                self.queue_message(MessageKind::Tool, format!("cleared agent: {agent_id}"));
            }
            None => {
                self.queue_message(MessageKind::System, "no agent override is active");
            }
        }
        self.status = format!("agent  {}", self.session_id);
    }

    pub fn set_agent_mode_selection(&mut self, mode: String) {
        self.agent_mode = mode.clone();
        self.backend_restart_requested = true;
        self.queue_message(MessageKind::Tool, format!("agent mode set: {mode}"));
        self.status = format!("mode  {}", self.session_id);
    }

    pub fn queue_agent_status(&mut self) {
        self.queue_message(
            MessageKind::System,
            format!(
                "agent_id: {}\nagent_mode: {}",
                self.selected_agent_id
                    .clone()
                    .unwrap_or_else(|| "(default)".to_string()),
                self.agent_mode
            ),
        );
        self.status = format!("agent  {}", self.session_id);
    }
}

pub(crate) fn normalize_agent_mode(value: &str) -> Option<String> {
    let normalized = value.trim().to_lowercase();
    VALID_AGENT_MODES
        .contains(&normalized.as_str())
        .then_some(normalized)
}
