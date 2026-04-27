use crate::app::{App, MessageKind};

impl App {
    pub fn set_model_override(&mut self, model: String) {
        self.selected_model = Some(model.clone());
        self.backend_restart_requested = true;
        self.queue_message(MessageKind::Tool, format!("model override set: {model}"));
        self.status = format!("model  {}", self.session_id);
    }

    pub fn clear_model_override(&mut self) {
        match self.selected_model.take() {
            Some(model) => {
                self.backend_restart_requested = true;
                self.queue_message(
                    MessageKind::Tool,
                    format!("cleared model override: {model}"),
                );
            }
            None => {
                self.queue_message(MessageKind::System, "no model override is active");
            }
        }
        self.status = format!("model  {}", self.session_id);
    }
}
