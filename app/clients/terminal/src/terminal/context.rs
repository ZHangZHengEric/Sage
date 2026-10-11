use crate::app::{App, MessageKind};
use crate::backend::{list_agents, list_providers, list_skills, SessionDetail};

pub(crate) fn sync_contextual_popup_data(app: &mut App) {
    if app.needs_agent_catalog() {
        if let Ok(agents) = list_agents(&app.user_id) {
            app.set_agent_catalog(
                agents
                    .into_iter()
                    .map(|agent| {
                        (
                            agent.agent_id,
                            agent.name,
                            agent.agent_mode,
                            agent.is_default,
                            agent.updated_at,
                        )
                    })
                    .collect(),
            );
        }
    }
    if app.needs_provider_catalog() {
        if let Ok(providers) = list_providers(&app.user_id) {
            app.set_provider_catalog(
                providers
                    .into_iter()
                    .map(|provider| {
                        (
                            provider.id,
                            provider.name,
                            provider.model,
                            provider.base_url,
                            provider.is_default,
                        )
                    })
                    .collect(),
            );
        }
    }
    if app.needs_skill_catalog() {
        if let Ok(skills) = list_skills(
            &app.user_id,
            app.selected_agent_id.as_deref(),
            app.workspace_override_path(),
        ) {
            app.set_skill_catalog(
                skills
                    .into_iter()
                    .map(|skill| (skill.name, skill.description, skill.source))
                    .collect(),
            );
        }
    }
}

pub(crate) fn apply_resumed_session(app: &mut App, detail: SessionDetail) {
    let recent_messages = detail
        .recent_messages
        .into_iter()
        .filter_map(|message| {
            let kind = match message.role.as_str() {
                "user" => MessageKind::User,
                "assistant" => MessageKind::Assistant,
                "tool" => MessageKind::Tool,
                _ => MessageKind::System,
            };
            if message.content.trim().is_empty() {
                None
            } else {
                Some((kind, message.content))
            }
        })
        .collect::<Vec<_>>();

    app.load_resumed_session(detail.session_id, recent_messages);
}
