use crate::app::{App, MessageKind, SubmitAction};
use crate::app_preview::provider_help_text;
use crate::display_policy::display_mode_name;
use crate::slash_command;

use super::agent::normalize_agent_mode;
use super::display::parse_display_mode;

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
            "/sessions" => match (parts.next(), parts.next(), parts.next()) {
                (None, None, None) => SubmitAction::OpenSessionPicker {
                    mode: crate::app::SessionPickerMode::Browse,
                    limit: 10,
                },
                (Some(value), None, None) => match value.parse::<usize>() {
                    Ok(limit) if limit > 0 => SubmitAction::OpenSessionPicker {
                        mode: crate::app::SessionPickerMode::Browse,
                        limit,
                    },
                    _ => {
                        self.queue_message(
                            MessageKind::System,
                            "Usage: /sessions [positive_limit] | /sessions inspect <latest|session_id>",
                        );
                        self.status = format!("invalid command  {}", self.session_id);
                        SubmitAction::Handled
                    }
                },
                (Some("inspect"), Some("latest"), None) => {
                    SubmitAction::ShowSession("latest".to_string())
                }
                (Some("inspect"), Some(session_id), None) => {
                    SubmitAction::ShowSession(session_id.to_string())
                }
                _ => {
                    self.queue_message(
                        MessageKind::System,
                        "Usage: /sessions [positive_limit] | /sessions inspect <latest|session_id>",
                    );
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
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
            "/config" => match (parts.next(), parts.next(), parts.next()) {
                (None, None, None) => SubmitAction::ShowConfig,
                (Some("init"), None, None) => SubmitAction::InitConfig {
                    path: None,
                    force: false,
                },
                (Some("init"), Some(flag), None) if flag == "--force" => SubmitAction::InitConfig {
                    path: None,
                    force: true,
                },
                (Some("init"), Some(path), None) => SubmitAction::InitConfig {
                    path: Some(path.to_string()),
                    force: false,
                },
                (Some("init"), Some(path), Some(flag)) if flag == "--force" => {
                    SubmitAction::InitConfig {
                        path: Some(path.to_string()),
                        force: true,
                    }
                }
                _ => {
                    self.queue_message(
                        MessageKind::System,
                        "Usage: /config | /config init [path] [--force]",
                    );
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/doctor" => match (parts.next(), parts.next()) {
                (None, None) => SubmitAction::ShowDoctor {
                    probe_provider: false,
                },
                (Some("probe-provider" | "--probe-provider"), None) => SubmitAction::ShowDoctor {
                    probe_provider: true,
                },
                _ => {
                    self.queue_message(MessageKind::System, "Usage: /doctor [probe-provider]");
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/providers" => {
                if parts.next().is_some() {
                    self.queue_message(MessageKind::System, "Usage: /providers");
                    self.status = format!("invalid command  {}", self.session_id);
                    return SubmitAction::Handled;
                }
                SubmitAction::ListProviders
            }
            "/provider" => {
                let subcommand = parts.next();
                let rest = parts.map(ToString::to_string).collect::<Vec<_>>();
                match subcommand.as_deref() {
                    None | Some("help") if rest.is_empty() => {
                        self.queue_message(MessageKind::Tool, provider_help_text());
                        self.status = format!("provider help  {}", self.session_id);
                        SubmitAction::Handled
                    }
                    Some("inspect") if rest.len() == 1 => {
                        SubmitAction::ShowProvider(rest[0].clone())
                    }
                    Some("verify") => SubmitAction::VerifyProvider(rest),
                    Some("default") if rest.len() == 1 => {
                        SubmitAction::SetDefaultProvider(rest[0].clone())
                    }
                    Some("delete") if rest.len() == 1 => {
                        SubmitAction::DeleteProvider(rest[0].clone())
                    }
                    Some("create") => SubmitAction::CreateProvider(rest),
                    Some("update") if !rest.is_empty() => SubmitAction::UpdateProvider {
                        provider_id: rest[0].clone(),
                        fields: rest[1..].to_vec(),
                    },
                    _ => {
                        self.queue_message(MessageKind::System, provider_help_text());
                        self.status = format!("invalid command  {}", self.session_id);
                        SubmitAction::Handled
                    }
                }
            }
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
            "/agent" => match (parts.next(), parts.next(), parts.next()) {
                (None, None, None) | (Some("show"), None, None) => {
                    self.queue_agent_status();
                    SubmitAction::Handled
                }
                (Some("list"), None, None) => SubmitAction::ListAgents,
                (Some("set"), Some(agent_id), None) => {
                    self.set_selected_agent_id(agent_id.to_string());
                    SubmitAction::Handled
                }
                (Some("clear"), None, None) => {
                    self.clear_selected_agent_id();
                    SubmitAction::Handled
                }
                _ => {
                    self.queue_message(
                        MessageKind::System,
                        "Usage: /agent | /agent show | /agent list | /agent set <agent_id> | /agent clear",
                    );
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/mode" => match (parts.next(), parts.next(), parts.next()) {
                (None, None, None) | (Some("show"), None, None) => {
                    self.queue_message(
                        MessageKind::System,
                        format!("agent_mode: {}", self.agent_mode),
                    );
                    self.status = format!("mode  {}", self.session_id);
                    SubmitAction::Handled
                }
                (Some("set"), Some(mode), None) => match normalize_agent_mode(mode) {
                    Some(mode) => {
                        self.set_agent_mode_selection(mode);
                        SubmitAction::Handled
                    }
                    None => {
                        self.queue_message(
                            MessageKind::System,
                            "Usage: /mode | /mode show | /mode set <simple|multi|fibre>",
                        );
                        self.status = format!("invalid command  {}", self.session_id);
                        SubmitAction::Handled
                    }
                },
                _ => {
                    self.queue_message(
                        MessageKind::System,
                        "Usage: /mode | /mode show | /mode set <simple|multi|fibre>",
                    );
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/display" => match (parts.next(), parts.next(), parts.next()) {
                (None, None, None) | (Some("show"), None, None) => {
                    self.queue_display_status();
                    SubmitAction::Handled
                }
                (Some("set"), Some(mode), None) => match parse_display_mode(mode) {
                    Some(mode) => {
                        self.set_display_mode(mode);
                        SubmitAction::Handled
                    }
                    None => {
                        self.queue_message(
                            MessageKind::System,
                            "Usage: /display | /display show | /display set <compact|verbose>",
                        );
                        self.status = format!("invalid command  {}", self.session_id);
                        SubmitAction::Handled
                    }
                },
                _ => {
                    self.queue_message(
                        MessageKind::System,
                        "Usage: /display | /display show | /display set <compact|verbose>",
                    );
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/workspace" => {
                let subcommand = parts.next();
                let rest = parts.map(ToString::to_string).collect::<Vec<_>>();
                match subcommand {
                    None | Some("show") if rest.is_empty() => {
                        self.queue_workspace_status();
                        SubmitAction::Handled
                    }
                    Some("set") if !rest.is_empty() => {
                        self.set_workspace_selection(rest.join(" "));
                        SubmitAction::Handled
                    }
                    Some("clear") if rest.is_empty() => {
                        self.clear_workspace_override_selection();
                        SubmitAction::Handled
                    }
                    _ => {
                        self.queue_message(
                            MessageKind::System,
                            "Usage: /workspace | /workspace show | /workspace set <path> | /workspace clear",
                        );
                        self.status = format!("invalid command  {}", self.session_id);
                        SubmitAction::Handled
                    }
                }
            }
            "/interrupt" => match (parts.next(), parts.next()) {
                (None, None) => SubmitAction::Interrupt,
                _ => {
                    self.queue_message(MessageKind::System, "Usage: /interrupt");
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/retry" => match (parts.next(), parts.next()) {
                (None, None) => SubmitAction::RetryLastTask,
                _ => {
                    self.queue_message(MessageKind::System, "Usage: /retry");
                    self.status = format!("invalid command  {}", self.session_id);
                    SubmitAction::Handled
                }
            },
            "/status" => {
                self.queue_message(
                    MessageKind::System,
                    format!(
                        "session: {}\nbusy: {}\nagent_id: {}\nagent_mode: {}\ndisplay_mode: {}\nworkspace: {}\nmax_loop_count: {}\nskills: {}\nmodel_override: {}\ninput: {} chars",
                        self.session_id,
                        self.busy,
                        self.selected_agent_id
                            .clone()
                            .unwrap_or_else(|| "(default)".to_string()),
                        self.agent_mode,
                        display_mode_name(self.display_mode),
                        self.workspace_label,
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
