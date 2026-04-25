use std::path::PathBuf;

use anyhow::{anyhow, Result};

use crate::app::{App, MessageKind};
use crate::backend::{
    list_providers, list_skills, ConfigInfo, ProviderInfo, ProviderMutation, SessionDetail,
    SkillInfo,
};

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

pub(crate) fn format_session_detail(detail: &SessionDetail) -> String {
    let mut lines = vec![format!(
        "{}  {} msgs  {}",
        detail.session_id, detail.message_count, detail.updated_at
    )];
    lines.push(detail.title.clone());
    for message in detail.recent_messages.iter().take(6) {
        if message.content.trim().is_empty() {
            continue;
        }
        lines.push(String::new());
        lines.push(format!("{}:", message.role));
        lines.push(message.content.trim().to_string());
    }
    lines.join("\n")
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

pub(crate) fn format_skills_list(skills: &[SkillInfo], active_skills: &[String]) -> String {
    let active = if active_skills.is_empty() {
        "(none)".to_string()
    } else {
        active_skills.join(", ")
    };

    if skills.is_empty() {
        return format!(
            "visible skills: none\nactive skills: {active}\n\nTip: this workspace currently exposes no CLI skills."
        );
    }

    let mut lines = vec![
        format!("active skills: {active}"),
        String::new(),
        "visible skills".to_string(),
    ];

    for skill in skills {
        lines.push(format!("{}  [{}]", skill.name, skill.source));
        if !skill.description.trim().is_empty() {
            lines.push(format!("  {}", skill.description.trim()));
        }
    }

    lines.join("\n")
}

pub(crate) fn format_config(config: &ConfigInfo, selected_model: &Option<String>) -> String {
    let active_model = selected_model
        .clone()
        .unwrap_or_else(|| config.default_model_name.clone());
    let model_source = if selected_model.is_some() {
        "session override"
    } else {
        "CLI default"
    };

    format!(
        "config\nuser: {}\nenv file: {}\nbase url: {}\ndefault model: {}\nactive model: {} ({})",
        config.default_user_id,
        config.env_file,
        config.default_api_base_url,
        config.default_model_name,
        active_model,
        model_source
    )
}

pub(crate) fn format_providers(providers: &[ProviderInfo]) -> String {
    if providers.is_empty() {
        return "providers: none\n\nTip: provider list is empty in the current CLI state."
            .to_string();
    }

    let mut lines = vec!["providers".to_string()];
    for provider in providers {
        lines.push(format!(
            "{}{}",
            provider.name,
            if provider.is_default {
                "  [default]"
            } else {
                ""
            }
        ));
        lines.push(format!("  id: {}", provider.id));
        lines.push(format!("  model: {}", provider.model));
        lines.push(format!("  base: {}", provider.base_url));
    }
    lines.join("\n")
}

pub(crate) fn format_provider_detail(provider: &ProviderInfo) -> String {
    format!(
        "{}{}\nid: {}\nmodel: {}\nbase: {}\napi key: {}",
        provider.name,
        if provider.is_default {
            "  [default]"
        } else {
            ""
        },
        provider.id,
        provider.model,
        provider.base_url,
        if provider.api_key_preview.is_empty() {
            "(hidden)"
        } else {
            &provider.api_key_preview
        }
    )
}

pub(crate) fn parse_provider_mutation(
    fields: &[String],
    require_core_fields: bool,
) -> Result<ProviderMutation> {
    let mut mutation = ProviderMutation {
        name: None,
        base_url: None,
        api_key: None,
        model: None,
        is_default: None,
    };

    for field in fields {
        let (raw_key, raw_value) = field
            .split_once('=')
            .ok_or_else(|| anyhow!("expected key=value field, got `{field}`"))?;
        let key = raw_key.trim();
        let value = raw_value.trim();
        match key {
            "name" => assign_provider_field(&mut mutation.name, "name", value)?,
            "base" | "base_url" => assign_provider_field(&mut mutation.base_url, "base", value)?,
            "key" | "api_key" => assign_provider_field(&mut mutation.api_key, "key", value)?,
            "model" => assign_provider_field(&mut mutation.model, "model", value)?,
            "default" => {
                if mutation.is_default.is_some() {
                    return Err(anyhow!(
                        "duplicate provider field `default`; supply it once"
                    ));
                }
                mutation.is_default = Some(parse_provider_bool(value)?);
            }
            other => {
                return Err(anyhow!(
                    "unknown provider field `{other}`; use name= model= base= key= default=true|false"
                ));
            }
        }
    }

    if require_core_fields {
        let mut missing = Vec::new();
        if mutation.name.is_none() {
            missing.push("name");
        }
        if mutation.model.is_none() {
            missing.push("model");
        }
        if mutation.base_url.is_none() {
            missing.push("base");
        }
        if !missing.is_empty() {
            return Err(anyhow!(
                "provider create requires name=..., model=..., base=...; missing: {}",
                missing.join(", ")
            ));
        }
    }

    if !require_core_fields
        && mutation.name.is_none()
        && mutation.model.is_none()
        && mutation.base_url.is_none()
        && mutation.api_key.is_none()
        && mutation.is_default.is_none()
    {
        return Err(anyhow!(
            "provider update requires at least one key=value field"
        ));
    }

    Ok(mutation)
}

fn assign_provider_field(slot: &mut Option<String>, field_name: &str, value: &str) -> Result<()> {
    if slot.is_some() {
        return Err(anyhow!(
            "duplicate provider field `{field_name}`; supply it once"
        ));
    }
    if value.is_empty() {
        return Err(anyhow!("provider field `{field_name}` cannot be empty"));
    }
    *slot = Some(value.to_string());
    Ok(())
}

fn parse_provider_bool(value: &str) -> Result<bool> {
    match value {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => Err(anyhow!(
            "invalid default value `{value}`; use true/false, yes/no, on/off, or 1/0"
        )),
    }
}
