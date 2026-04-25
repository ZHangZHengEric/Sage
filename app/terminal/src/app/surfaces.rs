use ratatui::text::Line;

use crate::app_preview::session_picker_preview_lines;
use crate::bottom_pane::command_popup;
use crate::bottom_pane::help_overlay;
use crate::bottom_pane::picker_overlay;
use crate::bottom_pane::transcript_overlay;
use crate::slash_command;

use super::{
    ActiveSurfaceKind, App, FilteredSessionPicker, ProviderCandidate, ProviderPopupMode,
    SessionPickerEntry, SessionPickerMode, SessionPickerState, SkillCandidate, SkillPopupMode,
    SubmitAction, TranscriptOverlayState,
};

impl App {
    pub fn active_surface_kind(&self) -> Option<ActiveSurfaceKind> {
        if self.help_overlay_visible {
            Some(ActiveSurfaceKind::Help)
        } else if self.session_picker.is_some() {
            Some(ActiveSurfaceKind::SessionPicker)
        } else if self.transcript_overlay.is_some() {
            Some(ActiveSurfaceKind::Transcript)
        } else if !self.popup_matches().is_empty() {
            Some(ActiveSurfaceKind::Popup)
        } else {
            None
        }
    }

    pub fn popup_matches(&self) -> Vec<command_popup::CommandMatch> {
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

    pub fn help_overlay_props(&self) -> Option<help_overlay::HelpOverlayProps> {
        if !self.help_overlay_visible {
            return None;
        }
        let (title, sections) = match self.help_overlay_topic.as_deref() {
            Some(topic) => {
                let command = slash_command::find(topic)?;
                (
                    format!("Help  {}", command.command),
                    vec![
                        help_overlay::HelpSection {
                            title: "Command".to_string(),
                            items: vec![help_overlay::HelpItem {
                                label: command.command.to_string(),
                                value: command.description.to_string(),
                            }],
                        },
                        help_overlay::HelpSection {
                            title: "Usage".to_string(),
                            items: vec![help_overlay::HelpItem {
                                label: String::new(),
                                value: command.usage.to_string(),
                            }],
                        },
                        help_overlay::HelpSection {
                            title: "Example".to_string(),
                            items: vec![help_overlay::HelpItem {
                                label: String::new(),
                                value: command.example.to_string(),
                            }],
                        },
                    ],
                )
            }
            None => (
                "Sage Terminal Help".to_string(),
                vec![
                    help_overlay::HelpSection {
                        title: "Commands".to_string(),
                        items: slash_command::all()
                            .iter()
                            .map(|command| help_overlay::HelpItem {
                                label: command.command.to_string(),
                                value: command.description.to_string(),
                            })
                            .collect(),
                    },
                    help_overlay::HelpSection {
                        title: "Tips".to_string(),
                        items: vec![help_overlay::HelpItem {
                            label: String::new(),
                            value: "Use /help <command> for usage and examples.".to_string(),
                        }],
                    },
                ],
            ),
        };
        Some(help_overlay::HelpOverlayProps {
            title,
            sections,
            footer_hint: "esc or enter to close".to_string(),
        })
    }

    pub fn close_help_overlay(&mut self) -> bool {
        if !self.help_overlay_visible {
            return false;
        }
        self.help_overlay_visible = false;
        self.help_overlay_topic = None;
        self.status = format!("ready  {}", self.session_id);
        true
    }

    pub fn is_help_overlay_visible(&self) -> bool {
        self.help_overlay_visible
    }

    pub fn close_active_surface(&mut self) -> bool {
        match self.active_surface_kind() {
            Some(ActiveSurfaceKind::Help) => self.close_help_overlay(),
            Some(ActiveSurfaceKind::SessionPicker) => self.close_session_picker(),
            Some(ActiveSurfaceKind::Transcript) => self.close_transcript_overlay(),
            Some(ActiveSurfaceKind::Popup) => {
                if self.input.is_empty() {
                    false
                } else {
                    self.clear_input();
                    true
                }
            }
            None => false,
        }
    }

    pub fn submit_active_surface(&mut self) -> Option<SubmitAction> {
        match self.active_surface_kind() {
            Some(ActiveSurfaceKind::Help) => {
                self.close_help_overlay();
                Some(SubmitAction::Handled)
            }
            Some(ActiveSurfaceKind::SessionPicker) => self.submit_session_picker_selection(),
            Some(ActiveSurfaceKind::Transcript) => {
                self.close_transcript_overlay();
                Some(SubmitAction::Handled)
            }
            Some(ActiveSurfaceKind::Popup) => self.submit_selected_popup(),
            None => None,
        }
    }

    pub fn select_next_active_surface_item(&mut self) -> bool {
        match self.active_surface_kind() {
            Some(ActiveSurfaceKind::SessionPicker) => self.select_next_session_picker_item(),
            Some(ActiveSurfaceKind::Transcript) => self.scroll_transcript_overlay_down(1),
            Some(ActiveSurfaceKind::Popup) => self.select_next_popup_item(),
            _ => false,
        }
    }

    pub fn select_previous_active_surface_item(&mut self) -> bool {
        match self.active_surface_kind() {
            Some(ActiveSurfaceKind::SessionPicker) => self.select_previous_session_picker_item(),
            Some(ActiveSurfaceKind::Transcript) => self.scroll_transcript_overlay_up(1),
            Some(ActiveSurfaceKind::Popup) => self.select_previous_popup_item(),
            _ => false,
        }
    }

    pub fn open_session_picker(&mut self, mode: SessionPickerMode, items: Vec<SessionPickerEntry>) {
        self.session_picker = Some(SessionPickerState {
            mode,
            items,
            filter_query: String::new(),
            selected: 0,
        });
        self.help_overlay_visible = false;
        self.help_overlay_topic = None;
        self.transcript_overlay = None;
        self.status = format!("session picker  {}", self.session_id);
    }

    pub fn session_picker_props(&self) -> Option<picker_overlay::PickerOverlayProps> {
        let picker = self.session_picker.as_ref()?;
        let filtered = self.filtered_session_picker_items()?;
        let selected_item = filtered
            .items
            .get(picker.selected)
            .map(|(_, item)| *item)
            .or_else(|| filtered.items.first().map(|(_, item)| *item));
        let title = match picker.mode {
            SessionPickerMode::Resume => "Resume Session",
            SessionPickerMode::Browse => "Recent Sessions",
        };
        let footer_hint = match picker.mode {
            SessionPickerMode::Resume => "type filter • ↑/↓ select • enter resume • esc close",
            SessionPickerMode::Browse => "type filter • ↑/↓ select • enter inspect • esc close",
        };
        let (preview_title, preview_lines) = selected_item
            .map(|item| {
                (
                    Some("Selected Session".to_string()),
                    session_picker_preview_lines(item, picker.mode),
                )
            })
            .unwrap_or_else(|| {
                (
                    Some("Preview".to_string()),
                    vec!["No matching sessions.".to_string()],
                )
            });
        Some(picker_overlay::PickerOverlayProps {
            title: title.to_string(),
            query: picker.filter_query.clone(),
            items: filtered
                .items
                .into_iter()
                .map(|(idx, item)| picker_overlay::PickerOverlayItem {
                    primary: item.session_id.clone(),
                    secondary: format!(
                        "{}  •  {} msgs  •  {}{}",
                        item.title,
                        item.message_count,
                        item.updated_at,
                        item.preview
                            .as_ref()
                            .map(|preview| format!("  •  {}", preview))
                            .unwrap_or_default()
                    ),
                    selected: idx == picker.selected,
                })
                .collect(),
            preview_title,
            preview_lines,
            footer_hint: footer_hint.to_string(),
        })
    }

    pub fn close_session_picker(&mut self) -> bool {
        if self.session_picker.is_none() {
            return false;
        }
        self.session_picker = None;
        self.status = format!("ready  {}", self.session_id);
        true
    }

    pub fn is_session_picker_visible(&self) -> bool {
        self.session_picker.is_some()
    }

    pub fn open_transcript_overlay(&mut self) {
        self.help_overlay_visible = false;
        self.help_overlay_topic = None;
        self.session_picker = None;
        self.transcript_overlay = Some(TranscriptOverlayState { scroll: 0 });
        self.status = format!("transcript  {}", self.session_id);
    }

    pub fn transcript_overlay_props(
        &self,
        viewport_width: u16,
    ) -> Option<transcript_overlay::TranscriptOverlayProps> {
        let overlay = self.transcript_overlay?;
        let lines = self.transcript_lines();
        let line_count = lines.len();
        let max_scroll = max_transcript_scroll_for_lines(&lines, viewport_width);
        Some(transcript_overlay::TranscriptOverlayProps {
            title: "Transcript".to_string(),
            lines,
            scroll: overlay.scroll.min(max_scroll),
            footer_hint: "↑/↓ scroll • pgup/pgdn jump • esc close".to_string(),
            status: if line_count == 0 {
                "empty transcript".to_string()
            } else {
                format!("{line_count} committed lines")
            },
        })
    }

    pub fn close_transcript_overlay(&mut self) -> bool {
        if self.transcript_overlay.is_none() {
            return false;
        }
        self.transcript_overlay = None;
        self.status = format!("ready  {}", self.session_id);
        true
    }

    pub fn scroll_transcript_overlay_up(&mut self, amount: u16) -> bool {
        let Some(overlay) = self.transcript_overlay.as_mut() else {
            return false;
        };
        let old = overlay.scroll;
        overlay.scroll = overlay.scroll.saturating_sub(amount);
        overlay.scroll != old
    }

    pub fn scroll_transcript_overlay_down(&mut self, amount: u16) -> bool {
        let max_scroll = max_transcript_scroll_for_lines(&self.transcript_lines(), 92);
        let Some(overlay) = self.transcript_overlay.as_mut() else {
            return false;
        };
        let old = overlay.scroll;
        overlay.scroll = overlay.scroll.saturating_add(amount).min(max_scroll);
        overlay.scroll != old
    }

    pub fn page_transcript_overlay_down(&mut self, amount: u16) -> bool {
        self.scroll_transcript_overlay_down(amount.max(4))
    }

    pub fn page_transcript_overlay_up(&mut self, amount: u16) -> bool {
        self.scroll_transcript_overlay_up(amount.max(4))
    }

    fn transcript_lines(&self) -> Vec<Line<'static>> {
        self.committed_history_lines
            .iter()
            .chain(self.pending_history_lines.iter())
            .cloned()
            .collect()
    }

    pub fn select_next_session_picker_item(&mut self) -> bool {
        let visible = self
            .filtered_session_picker_items()
            .map(|items| items.items.len())
            .unwrap_or(0);
        if visible == 0 {
            return false;
        }
        let Some(picker) = self.session_picker.as_mut() else {
            return false;
        };
        picker.selected = (picker.selected + 1) % visible;
        true
    }

    pub fn select_previous_session_picker_item(&mut self) -> bool {
        let visible = self
            .filtered_session_picker_items()
            .map(|items| items.items.len())
            .unwrap_or(0);
        if visible == 0 {
            return false;
        }
        let Some(picker) = self.session_picker.as_mut() else {
            return false;
        };
        picker.selected = (picker.selected + visible.saturating_sub(1)) % visible;
        true
    }

    pub fn session_picker_insert_char(&mut self, ch: char) -> bool {
        let Some(picker) = self.session_picker.as_mut() else {
            return false;
        };
        picker.filter_query.push(ch);
        self.sync_session_picker_selection();
        true
    }

    pub fn session_picker_backspace(&mut self) -> bool {
        let Some(picker) = self.session_picker.as_mut() else {
            return false;
        };
        if picker.filter_query.pop().is_none() {
            return false;
        }
        self.sync_session_picker_selection();
        true
    }

    pub fn clear_session_picker_filter(&mut self) -> bool {
        let Some(picker) = self.session_picker.as_mut() else {
            return false;
        };
        if picker.filter_query.is_empty() {
            return false;
        }
        picker.filter_query.clear();
        self.sync_session_picker_selection();
        true
    }

    pub fn submit_session_picker_selection(&mut self) -> Option<SubmitAction> {
        let picker = self.session_picker.as_ref()?;
        let filtered = self.filtered_session_picker_items()?;
        let (_, item) = filtered.items.get(picker.selected)?;
        let session_id = item.session_id.clone();
        let mode = picker.mode;
        self.session_picker = None;
        Some(match mode {
            SessionPickerMode::Resume => SubmitAction::ResumeSession(session_id),
            SessionPickerMode::Browse => SubmitAction::ShowSession(session_id),
        })
    }

    pub fn needs_provider_catalog(&self) -> bool {
        self.provider_popup_context().is_some() && self.provider_catalog.is_none()
    }

    pub fn needs_skill_catalog(&self) -> bool {
        matches!(self.skill_popup_context(), Some((SkillPopupMode::Add, _)))
            && self.skill_catalog.is_none()
    }

    pub fn set_provider_catalog(&mut self, providers: Vec<(String, String, String, String, bool)>) {
        self.provider_catalog = Some(
            providers
                .into_iter()
                .map(
                    |(id, name, model, base_url, is_default)| ProviderCandidate {
                        id,
                        name,
                        model,
                        base_url,
                        is_default,
                    },
                )
                .collect(),
        );
        self.sync_slash_popup_selection();
    }

    pub fn clear_provider_catalog(&mut self) {
        self.provider_catalog = None;
    }

    pub fn set_skill_catalog(&mut self, skills: Vec<(String, String, String)>) {
        self.skill_catalog = Some(
            skills
                .into_iter()
                .map(|(name, description, source)| SkillCandidate {
                    name,
                    description,
                    source,
                })
                .collect(),
        );
        self.sync_slash_popup_selection();
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

    fn provider_popup_context(&self) -> Option<(ProviderPopupMode, &str)> {
        let line = self.input.lines().next().unwrap_or("");
        if let Some(query) = line.strip_prefix("/provider inspect ") {
            if query.split_whitespace().count() <= 1 {
                return Some((ProviderPopupMode::Inspect, query.trim()));
            }
        }
        if let Some(query) = line.strip_prefix("/provider default ") {
            if query.split_whitespace().count() <= 1 {
                return Some((ProviderPopupMode::Default, query.trim()));
            }
        }
        None
    }

    fn skill_popup_context(&self) -> Option<(SkillPopupMode, &str)> {
        let line = self.input.lines().next().unwrap_or("");
        if let Some(query) = line.strip_prefix("/skill add ") {
            if query.split_whitespace().count() <= 1 {
                return Some((SkillPopupMode::Add, query.trim()));
            }
        }
        if let Some(query) = line.strip_prefix("/skill remove ") {
            if query.split_whitespace().count() <= 1 {
                return Some((SkillPopupMode::Remove, query.trim()));
            }
        }
        None
    }

    fn provider_popup_matches(
        &self,
        mode: ProviderPopupMode,
        query: &str,
    ) -> Vec<command_popup::CommandMatch> {
        let Some(catalog) = self.provider_catalog.as_ref() else {
            return Vec::new();
        };

        let query = query.to_lowercase();
        let mut exact = Vec::new();
        let mut prefix = Vec::new();
        let mut contains = Vec::new();

        for provider in catalog {
            let id = provider.id.to_lowercase();
            let name = provider.name.to_lowercase();
            let matches = if query.is_empty() {
                1
            } else if id == query || name == query {
                3
            } else if id.starts_with(&query) || name.starts_with(&query) {
                2
            } else if id.contains(&query)
                || name.contains(&query)
                || provider.model.to_lowercase().contains(&query)
            {
                1
            } else {
                0
            };
            if matches == 0 {
                continue;
            }

            let description = format!(
                "{}  •  {}{}",
                provider.name,
                provider.model,
                if provider.is_default {
                    "  •  default"
                } else {
                    ""
                }
            );
            let action = match mode {
                ProviderPopupMode::Inspect => {
                    command_popup::PopupAction::ShowProvider(provider.id.clone())
                }
                ProviderPopupMode::Default => {
                    command_popup::PopupAction::SetDefaultProvider(provider.id.clone())
                }
            };
            let item = command_popup::CommandMatch {
                command: provider.id.clone(),
                description,
                preview_lines: vec![
                    format!("name: {}", provider.name),
                    format!("model: {}", provider.model),
                    format!("base: {}", provider.base_url),
                ],
                autocomplete: match mode {
                    ProviderPopupMode::Inspect => format!("/provider inspect {}", provider.id),
                    ProviderPopupMode::Default => format!("/provider default {}", provider.id),
                },
                action,
            };
            match matches {
                3 => exact.push(item),
                2 => prefix.push(item),
                _ => contains.push(item),
            }
        }

        exact.extend(prefix);
        exact.extend(contains);
        exact
    }

    fn skill_popup_matches(
        &self,
        mode: SkillPopupMode,
        query: &str,
    ) -> Vec<command_popup::CommandMatch> {
        let query = query.to_lowercase();
        let mut exact = Vec::new();
        let mut prefix = Vec::new();
        let mut contains = Vec::new();

        match mode {
            SkillPopupMode::Add => {
                let Some(catalog) = self.skill_catalog.as_ref() else {
                    return Vec::new();
                };
                for skill in catalog {
                    let name = skill.name.to_lowercase();
                    let description = skill.description.to_lowercase();
                    let matches = if query.is_empty() {
                        1
                    } else if name == query {
                        3
                    } else if name.starts_with(&query) {
                        2
                    } else if name.contains(&query)
                        || description.contains(&query)
                        || skill.source.to_lowercase().contains(&query)
                    {
                        1
                    } else {
                        0
                    };
                    if matches == 0 {
                        continue;
                    }

                    let active = self.selected_skills.iter().any(|item| item == &skill.name);
                    let item = command_popup::CommandMatch {
                        command: skill.name.clone(),
                        description: format!(
                            "{}{}",
                            skill.source,
                            if active { "  •  active" } else { "" }
                        ),
                        preview_lines: vec![
                            format!("source: {}", skill.source),
                            format!(
                                "description: {}",
                                if skill.description.trim().is_empty() {
                                    "(none)"
                                } else {
                                    skill.description.trim()
                                }
                            ),
                            if active {
                                "status: already active".to_string()
                            } else {
                                "status: ready to add".to_string()
                            },
                        ],
                        autocomplete: format!("/skill add {}", skill.name),
                        action: command_popup::PopupAction::EnableSkill(skill.name.clone()),
                    };
                    match matches {
                        3 => exact.push(item),
                        2 => prefix.push(item),
                        _ => contains.push(item),
                    }
                }
            }
            SkillPopupMode::Remove => {
                let selected = self
                    .selected_skills
                    .iter()
                    .map(|name| {
                        let details = self
                            .skill_catalog
                            .as_ref()
                            .and_then(|catalog| catalog.iter().find(|item| item.name == *name));
                        (
                            name.clone(),
                            details
                                .map(|item| item.description.clone())
                                .unwrap_or_default(),
                            details
                                .map(|item| item.source.clone())
                                .unwrap_or_else(|| "selected".to_string()),
                        )
                    })
                    .collect::<Vec<_>>();
                for (name, description, source) in selected {
                    let lowered = name.to_lowercase();
                    let matches = if query.is_empty() {
                        1
                    } else if lowered == query {
                        3
                    } else if lowered.starts_with(&query) {
                        2
                    } else if lowered.contains(&query)
                        || description.to_lowercase().contains(&query)
                        || source.to_lowercase().contains(&query)
                    {
                        1
                    } else {
                        0
                    };
                    if matches == 0 {
                        continue;
                    }

                    let item = command_popup::CommandMatch {
                        command: name.clone(),
                        description: format!("{source}  •  active"),
                        preview_lines: vec![
                            format!("source: {source}"),
                            format!(
                                "description: {}",
                                if description.trim().is_empty() {
                                    "(none)"
                                } else {
                                    description.trim()
                                }
                            ),
                            "status: will be removed".to_string(),
                        ],
                        autocomplete: format!("/skill remove {name}"),
                        action: command_popup::PopupAction::DisableSkill(name),
                    };
                    match matches {
                        3 => exact.push(item),
                        2 => prefix.push(item),
                        _ => contains.push(item),
                    }
                }
            }
        }

        exact.extend(prefix);
        exact.extend(contains);
        exact
    }

    pub(super) fn filtered_session_picker_items(&self) -> Option<FilteredSessionPicker<'_>> {
        let picker = self.session_picker.as_ref()?;
        let query = picker.filter_query.trim().to_lowercase();
        let items = picker
            .items
            .iter()
            .enumerate()
            .filter(|(_, item)| {
                if query.is_empty() {
                    return true;
                }
                item.session_id.to_lowercase().contains(&query)
                    || item.title.to_lowercase().contains(&query)
                    || item
                        .preview
                        .as_ref()
                        .is_some_and(|preview| preview.to_lowercase().contains(&query))
            })
            .collect::<Vec<_>>();
        Some(FilteredSessionPicker { items })
    }
}

fn transcript_body_height(props: &transcript_overlay::TranscriptOverlayProps) -> u16 {
    transcript_overlay::required_height(props).saturating_sub(2)
}

fn max_transcript_scroll_for_lines(lines: &[Line<'static>], viewport_width: u16) -> u16 {
    let props = transcript_overlay::TranscriptOverlayProps {
        title: "Transcript".to_string(),
        lines: lines.to_vec(),
        scroll: 0,
        footer_hint: String::new(),
        status: String::new(),
    };
    let total = transcript_overlay::wrapped_line_count(&props, viewport_width);
    let body = transcript_body_height(&props);
    total.saturating_sub(body)
}
