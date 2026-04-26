use crate::app::{App, MessageKind, SubmitAction};
use crate::app_preview::provider_help_text;
use crate::slash_command;

impl App {
    pub(crate) fn handle_command(&mut self, command: &str) -> SubmitAction {
        let mut parts = command.split_whitespace();
        let Some(head) = parts.next() else {
            return SubmitAction::Noop;
        };

        match head {
            "/help" => match (parts.next(), parts.next()) {
                (None, None) => {
                    self.help_overlay_visible = true;
                    self.help_overlay_topic = None;
                    self.transcript_overlay = None;
                    self.status = format!("help  {}", self.session_id);
                    SubmitAction::Handled
                }
                (Some(topic), None) => {
                    let Some(command) = slash_command::find(topic) else {
                        self.queue_message(
                            MessageKind::System,
                            format!("unknown help topic: {topic}\nTry /help to list commands."),
                        );
                        self.status = format!("invalid command  {}", self.session_id);
                        return SubmitAction::Handled;
                    };
                    self.help_overlay_visible = true;
                    self.help_overlay_topic = Some(command.command.to_string());
                    self.transcript_overlay = None;
                    self.status = format!("help  {}", self.session_id);
                    SubmitAction::Handled
                }
                _ => {
                    self.queue_message(MessageKind::System, "Usage: /help [command]");
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/new" => {
                self.reset_session();
                SubmitAction::Handled
            }
            "/clear" => {
                self.pending_history_lines.clear();
                self.committed_history_lines.clear();
                self.live_message = None;
                self.live_message_had_history = false;
                self.clear_requested = true;
                self.status = format!("cleared  {}", self.session_id);
                self.queue_welcome_banner();
                SubmitAction::Handled
            }
            "/sessions" => {
                let limit = match parts.next() {
                    Some(value) => match value.parse::<usize>() {
                        Ok(limit) if limit > 0 => limit,
                        _ => {
                            self.queue_message(
                                MessageKind::System,
                                "Usage: /sessions [positive_limit]",
                            );
                            self.status = format!("invalid command  {}", self.session_id);
                            return SubmitAction::Handled;
                        }
                    },
                    None => 10,
                };
                if parts.next().is_some() {
                    self.queue_message(MessageKind::System, "Usage: /sessions [positive_limit]");
                    self.status = format!("invalid command  {}", self.session_id);
                    return SubmitAction::Handled;
                }
                SubmitAction::OpenSessionPicker {
                    mode: crate::app::SessionPickerMode::Browse,
                    limit,
                }
            }
            "/resume" => match (parts.next(), parts.next()) {
                (None, None) => SubmitAction::OpenSessionPicker {
                    mode: crate::app::SessionPickerMode::Resume,
                    limit: 10,
                },
                (Some("latest"), None) => SubmitAction::ResumeLatest,
                (Some(session_id), None) => SubmitAction::ResumeSession(session_id.to_string()),
                _ => {
                    self.queue_message(MessageKind::System, "Usage: /resume [latest|session_id]");
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/skills" => {
                if parts.next().is_some() {
                    self.queue_message(MessageKind::System, "Usage: /skills");
                    self.status = format!("invalid command  {}", self.session_id);
                    return SubmitAction::Handled;
                }
                SubmitAction::ListSkills
            }
            "/config" => {
                if parts.next().is_some() {
                    self.queue_message(MessageKind::System, "Usage: /config");
                    self.status = format!("invalid command  {}", self.session_id);
                    return SubmitAction::Handled;
                }
                SubmitAction::ShowConfig
            }
            "/providers" => {
                if parts.next().is_some() {
                    self.queue_message(MessageKind::System, "Usage: /providers");
                    self.status = format!("invalid command  {}", self.session_id);
                    return SubmitAction::Handled;
                }
                SubmitAction::ListProviders
            }
            "/provider" => match (parts.next(), parts.next(), parts.next()) {
                (None, None, None) | (Some("help"), None, None) => {
                    self.queue_message(MessageKind::Tool, provider_help_text());
                    self.status = format!("provider help  {}", self.session_id);
                    SubmitAction::Handled
                }
                (Some("inspect"), Some(provider_id), None) => {
                    SubmitAction::ShowProvider(provider_id.to_string())
                }
                (Some("default"), Some(provider_id), None) => {
                    SubmitAction::SetDefaultProvider(provider_id.to_string())
                }
                (Some("delete"), Some(provider_id), None) => {
                    SubmitAction::DeleteProvider(provider_id.to_string())
                }
                (Some("create"), _, _) => {
                    let fields = parts.map(ToString::to_string).collect::<Vec<_>>();
                    SubmitAction::CreateProvider(fields)
                }
                (Some("update"), Some(provider_id), _) => {
                    let fields = parts.map(ToString::to_string).collect::<Vec<_>>();
                    SubmitAction::UpdateProvider {
                        provider_id: provider_id.to_string(),
                        fields,
                    }
                }
                _ => {
                    self.queue_message(MessageKind::System, provider_help_text());
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/skill" => match (parts.next(), parts.next(), parts.next()) {
                (Some("add"), Some(name), None) => SubmitAction::EnableSkill(name.to_string()),
                (Some("remove"), Some(name), None) => SubmitAction::DisableSkill(name.to_string()),
                (Some("clear"), None, None) => SubmitAction::ClearSkills,
                _ => {
                    self.queue_message(
                        MessageKind::System,
                        "Usage: /skill add <name> | /skill remove <name> | /skill clear",
                    );
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/model" => match (parts.next(), parts.next(), parts.next()) {
                (None, None, None) => SubmitAction::ShowModel,
                (Some("show"), None, None) => SubmitAction::ShowModel,
                (Some("set"), Some(name), None) => SubmitAction::SetModel(name.to_string()),
                (Some("clear"), None, None) => SubmitAction::ClearModel,
                _ => {
                    self.queue_message(
                        MessageKind::System,
                        "Usage: /model | /model show | /model set <name> | /model clear",
                    );
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/status" => {
                self.queue_message(
                    MessageKind::System,
                    format!(
                        "session: {}\nbusy: {}\nagent_mode: {}\nmax_loop_count: {}\nskills: {}\nmodel_override: {}\ninput: {} chars",
                        self.session_id,
                        self.busy,
                        self.agent_mode,
                        self.max_loop_count,
                        if self.selected_skills.is_empty() {
                            "(none)".to_string()
                        } else {
                            self.selected_skills.join(", ")
                        },
                        self.selected_model
                            .clone()
                            .unwrap_or_else(|| "(none)".to_string()),
                        self.input.chars().count(),
                    ),
                );
                self.status = format!("status  {}", self.session_id);
                SubmitAction::Handled
            }
            "/transcript" => {
                self.open_transcript_overlay();
                SubmitAction::Handled
            }
            "/welcome" => {
                self.queue_welcome_banner();
                self.status = format!("welcome  {}", self.session_id);
                SubmitAction::Handled
            }
            "/exit" => {
                self.should_quit = true;
                SubmitAction::Handled
            }
            other => {
                self.queue_message(MessageKind::System, format!("Unknown command: {other}"));
                self.status = format!("unknown command  {}", self.session_id);
                SubmitAction::Handled
            }
        }
    }
}
