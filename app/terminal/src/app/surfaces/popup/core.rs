use crate::app::{App, SubmitAction};
use crate::bottom_pane::command_popup;
use crate::slash_command;

impl App {
    pub fn popup_matches(&self) -> Vec<command_popup::CommandMatch> {
        if let Some((mode, query)) = self.agent_popup_context() {
            return self.agent_popup_matches(mode, query);
        }
        if let Some((mode, query)) = self.provider_popup_context() {
            return self.provider_popup_matches(mode, query);
        }
        if let Some((mode, query)) = self.skill_popup_context() {
            return self.skill_popup_matches(mode, query);
        }
        command_popup::matching_commands(
            slash_command::all(),
            command_popup::popup_query(&self.input),
        )
    }

    pub fn popup_props(&self) -> Option<command_popup::CommandPopupProps> {
        let matches = self.popup_matches();
        command_popup::props_from_matches(&matches, self.slash_popup_selected)
    }

    pub fn needs_provider_catalog(&self) -> bool {
        self.provider_popup_context().is_some() && self.provider_catalog.is_none()
    }

    pub fn needs_agent_catalog(&self) -> bool {
        self.agent_popup_context().is_some() && self.agent_catalog.is_none()
    }

    pub fn needs_skill_catalog(&self) -> bool {
        matches!(
            self.skill_popup_context(),
            Some((crate::app::SkillPopupMode::Add, _))
        ) && self.skill_catalog.is_none()
    }

    pub fn select_next_popup_item(&mut self) -> bool {
        let matches = self.popup_matches();
        if matches.is_empty() {
            return false;
        }
        self.slash_popup_selected = (self.slash_popup_selected + 1) % matches.len();
        true
    }

    pub fn select_previous_popup_item(&mut self) -> bool {
        let matches = self.popup_matches();
        if matches.is_empty() {
            return false;
        }
        self.slash_popup_selected =
            (self.slash_popup_selected + matches.len().saturating_sub(1)) % matches.len();
        true
    }

    pub fn autocomplete_popup(&mut self) -> bool {
        let matches = self.popup_matches();
        let Some(item) = matches.get(self.slash_popup_selected) else {
            return false;
        };
        self.input = item.autocomplete.clone();
        self.input_cursor = self.input.len();
        self.sync_slash_popup_selection();
        true
    }

    pub fn submit_selected_popup(&mut self) -> Option<SubmitAction> {
        let matches = self.popup_matches();
        let action = matches.get(self.slash_popup_selected)?.action.clone();
        match action {
            command_popup::PopupAction::HandleCommand(command) => {
                self.clear_input();
                Some(self.handle_command(&command))
            }
            command_popup::PopupAction::ShowProvider(provider_id) => {
                self.clear_input();
                Some(SubmitAction::ShowProvider(provider_id))
            }
            command_popup::PopupAction::SetDefaultProvider(provider_id) => {
                self.clear_input();
                Some(SubmitAction::SetDefaultProvider(provider_id))
            }
            command_popup::PopupAction::EnableSkill(skill) => {
                self.clear_input();
                Some(SubmitAction::EnableSkill(skill))
            }
            command_popup::PopupAction::DisableSkill(skill) => {
                self.clear_input();
                Some(SubmitAction::DisableSkill(skill))
            }
        }
    }
}
