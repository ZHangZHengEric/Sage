use std::path::PathBuf;

use crate::app::{App, MessageKind};
use crate::backend::{list_providers, list_skills, SessionDetail};

pub(crate) fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

pub(crate) fn sync_contextual_popup_data(app: &mut App) {
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
        if let Ok(skills) = list_skills(&app.user_id, Some(repo_root().as_path())) {
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
