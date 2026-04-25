use anyhow::Result;

use crate::app::{App, MessageKind, SessionPickerEntry, SubmitAction};
use crate::backend::{
    create_provider, delete_provider, inspect_latest_session, inspect_provider, inspect_session,
    list_providers, list_sessions, list_skills, read_config, set_default_provider, update_provider,
    BackendHandle, BackendRequest,
};
use crate::terminal_support::{
    apply_resumed_session, format_config, format_provider_detail, format_providers,
    format_session_detail, format_skills_list, parse_provider_mutation, repo_root,
};

use super::{ensure_backend, stop_backend};

pub(super) fn handle_submit_action(
    app: &mut App,
    backend: &mut Option<BackendHandle>,
    action: SubmitAction,
) -> Result<bool> {
    match action {
        SubmitAction::Noop => Ok(false),
        SubmitAction::Handled => Ok(true),
        SubmitAction::RunTask(task) => {
            let request = BackendRequest {
                session_id: app.session_id.clone(),
                user_id: app.user_id.clone(),
                agent_mode: app.agent_mode.clone(),
                max_loop_count: app.max_loop_count,
                workspace: Some(repo_root()),
                skills: app.selected_skills.clone(),
                model_override: app.selected_model.clone(),
                task,
            };
            let handle = ensure_backend(backend, &request)?;
            handle.send_prompt(&request.task)?;
            Ok(true)
        }
        SubmitAction::OpenSessionPicker { mode, limit } => {
            match list_sessions(&app.user_id, limit) {
                Ok(sessions) if sessions.is_empty() => {
                    app.push_message(MessageKind::System, "no saved sessions available");
                    app.set_status(format!("resume unavailable  {}", app.session_id));
                }
                Ok(sessions) => {
                    app.open_session_picker(
                        mode,
                        sessions
                            .into_iter()
                            .map(|session| SessionPickerEntry {
                                session_id: session.session_id,
                                title: session.title,
                                message_count: session.message_count,
                                updated_at: session.updated_at,
                                preview: session.last_preview,
                            })
                            .collect(),
                    );
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to load sessions: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ListSkills => {
            match list_skills(&app.user_id, Some(repo_root().as_path())) {
                Ok(skills) => {
                    app.set_skill_catalog(
                        skills
                            .iter()
                            .map(|skill| {
                                (
                                    skill.name.clone(),
                                    skill.description.clone(),
                                    skill.source.clone(),
                                )
                            })
                            .collect(),
                    );
                    app.push_message(
                        MessageKind::Tool,
                        format_skills_list(&skills, &app.selected_skills),
                    );
                    app.set_status(format!("skills  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(MessageKind::System, format!("failed to list skills: {err}"));
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::EnableSkill(skill) => {
            match list_skills(&app.user_id, Some(repo_root().as_path())) {
                Ok(skills) => {
                    app.set_skill_catalog(
                        skills
                            .iter()
                            .map(|skill| {
                                (
                                    skill.name.clone(),
                                    skill.description.clone(),
                                    skill.source.clone(),
                                )
                            })
                            .collect(),
                    );
                    if skills.iter().any(|item| item.name == skill) {
                        app.enable_skill(skill);
                    } else {
                        app.push_message(
                            MessageKind::System,
                            format!(
                                "unknown skill: {skill}\nRun /skills to inspect visible skills."
                            ),
                        );
                        app.set_status(format!("skills  {}", app.session_id));
                    }
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to validate skill: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::DisableSkill(skill) => {
            app.disable_skill(&skill);
            Ok(true)
        }
        SubmitAction::ClearSkills => {
            app.clear_skills();
            Ok(true)
        }
        SubmitAction::ShowConfig => {
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
        SubmitAction::ListProviders => {
            match list_providers(&app.user_id) {
                Ok(providers) => {
                    app.set_provider_catalog(
                        providers
                            .iter()
                            .map(|provider| {
                                (
                                    provider.id.clone(),
                                    provider.name.clone(),
                                    provider.model.clone(),
                                    provider.base_url.clone(),
                                    provider.is_default,
                                )
                            })
                            .collect(),
                    );
                    app.push_message(MessageKind::Tool, format_providers(&providers));
                    app.set_status(format!("providers  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to list providers: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ShowProvider(provider_id) => {
            match inspect_provider(&app.user_id, &provider_id) {
                Ok(provider) => {
                    app.push_message(MessageKind::Tool, format_provider_detail(&provider));
                    app.set_status(format!("provider  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to inspect provider: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::SetDefaultProvider(provider_id) => {
            match set_default_provider(&app.user_id, &provider_id) {
                Ok(provider) => {
                    stop_backend(backend.take());
                    app.clear_provider_catalog();
                    app.push_message(
                        MessageKind::Tool,
                        format!(
                            "default provider set\n{}",
                            format_provider_detail(&provider)
                        ),
                    );
                    if !provider.model.is_empty() {
                        app.selected_model = None;
                    }
                    app.set_status(format!("provider  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to update provider: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::CreateProvider(fields) => {
            match parse_provider_mutation(&fields, true)
                .and_then(|mutation| create_provider(&app.user_id, &mutation))
            {
                Ok(provider) => {
                    stop_backend(backend.take());
                    app.clear_provider_catalog();
                    app.push_message(
                        MessageKind::Tool,
                        format!("provider created\n{}", format_provider_detail(&provider)),
                    );
                    app.set_status(format!("provider  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to create provider: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::UpdateProvider {
            provider_id,
            fields,
        } => {
            match parse_provider_mutation(&fields, false)
                .and_then(|mutation| update_provider(&app.user_id, &provider_id, &mutation))
            {
                Ok(provider) => {
                    stop_backend(backend.take());
                    app.clear_provider_catalog();
                    app.push_message(
                        MessageKind::Tool,
                        format!("provider updated\n{}", format_provider_detail(&provider)),
                    );
                    app.set_status(format!("provider  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to update provider: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::DeleteProvider(provider_id) => {
            match delete_provider(&app.user_id, &provider_id) {
                Ok(()) => {
                    stop_backend(backend.take());
                    app.clear_provider_catalog();
                    app.push_message(
                        MessageKind::Tool,
                        format!("provider deleted: {}", provider_id),
                    );
                    app.set_status(format!("provider  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to delete provider: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ShowModel => {
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
        SubmitAction::SetModel(model) => {
            app.set_model_override(model);
            Ok(true)
        }
        SubmitAction::ClearModel => {
            app.clear_model_override();
            Ok(true)
        }
        SubmitAction::ResumeLatest => {
            match inspect_latest_session(&app.user_id) {
                Ok(Some(detail)) => apply_resumed_session(app, detail),
                Ok(None) => {
                    app.push_message(MessageKind::System, "no saved sessions available");
                    app.set_status(format!("resume unavailable  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(MessageKind::System, format!("failed to resume: {err}"));
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ResumeSession(session_id) => {
            match inspect_session(&session_id, &app.user_id) {
                Ok(Some(detail)) => apply_resumed_session(app, detail),
                Ok(None) => {
                    app.push_message(
                        MessageKind::System,
                        format!("session not found: {session_id}"),
                    );
                    app.set_status(format!("resume unavailable  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(MessageKind::System, format!("failed to resume: {err}"));
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
        SubmitAction::ShowSession(session_id) => {
            match inspect_session(&session_id, &app.user_id) {
                Ok(Some(detail)) => {
                    app.push_message(MessageKind::Tool, format_session_detail(&detail));
                    app.set_status(format!("session  {}", app.session_id));
                }
                Ok(None) => {
                    app.push_message(
                        MessageKind::System,
                        format!("session not found: {session_id}"),
                    );
                    app.set_status(format!("session unavailable  {}", app.session_id));
                }
                Err(err) => {
                    app.push_message(
                        MessageKind::System,
                        format!("failed to inspect session: {err}"),
                    );
                    app.set_status(format!("error  {}", app.session_id));
                }
            }
            Ok(true)
        }
    }
}
