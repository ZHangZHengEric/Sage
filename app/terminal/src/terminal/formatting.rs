use crate::backend::{ConfigInfo, ProviderInfo, SessionDetail, SkillInfo};

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
