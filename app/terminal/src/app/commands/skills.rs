use crate::app::{App, MessageKind};

impl App {
    pub fn enable_skill(&mut self, skill: String) {
        if self.selected_skills.iter().any(|item| item == &skill) {
            self.queue_message(
                MessageKind::System,
                format!("skill already active: {skill}"),
            );
            self.status = format!("skill active  {}", self.session_id);
            return;
        }
        self.selected_skills.push(skill.clone());
        self.selected_skills.sort();
        self.backend_restart_requested = true;
        self.queue_message(MessageKind::Tool, format!("skill enabled: {skill}"));
        self.status = format!("skills  {}", self.session_id);
    }

    pub fn disable_skill(&mut self, skill: &str) {
        let previous_len = self.selected_skills.len();
        self.selected_skills.retain(|item| item != skill);
        if self.selected_skills.len() == previous_len {
            self.queue_message(MessageKind::System, format!("skill not active: {skill}"));
            self.status = format!("skills  {}", self.session_id);
            return;
        }
        self.backend_restart_requested = true;
        self.queue_message(MessageKind::Tool, format!("skill removed: {skill}"));
        self.status = format!("skills  {}", self.session_id);
    }

    pub fn clear_skills(&mut self) {
        let cleared = self.selected_skills.len();
        self.selected_skills.clear();
        self.backend_restart_requested = true;
        self.queue_message(
            MessageKind::Tool,
            format!("cleared {} active skill(s)", cleared),
        );
        self.status = format!("skills  {}", self.session_id);
    }
}
