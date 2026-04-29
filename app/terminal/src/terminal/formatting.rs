use serde_json::Value;

use crate::backend::{
    AgentInfo, ConfigInfo, ConfigInitInfo, ProviderInfo, ProviderVerifyInfo, SessionDetail,
    SkillInfo,
};

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

pub(crate) fn format_agents_list(agents: &[AgentInfo], selected_agent_id: Option<&str>) -> String {
    let active_agent = selected_agent_id.unwrap_or("(default)");
    if agents.is_empty() {
        return format!(
            "selected agent: {active_agent}\nvisible agents: none\n\nTip: this CLI state currently exposes no saved agents."
        );
    }

    let mut lines = vec![
        format!("selected agent: {active_agent}"),
        String::new(),
        "visible agents".to_string(),
    ];

    for agent in agents {
        lines.push(format!(
            "{}{}  [{}]",
            agent.name,
            if agent.is_default { "  [default]" } else { "" },
            agent.agent_mode,
        ));
        lines.push(format!("  id: {}", agent.agent_id));
        if !agent.updated_at.trim().is_empty() {
            lines.push(format!("  updated: {}", agent.updated_at));
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

pub(crate) fn format_config_init(result: &ConfigInitInfo) -> String {
    let mut lines = vec![
        "config initialized".to_string(),
        format!("path: {}", result.path),
        format!("template: {}", result.template),
        format!("overwritten: {}", result.overwritten),
    ];
    if !result.next_steps.is_empty() {
        lines.push(String::new());
        lines.push("next steps".to_string());
        lines.extend(result.next_steps.iter().map(|step| format!("- {step}")));
    }
    lines.join("\n")
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

pub(crate) fn format_provider_verify(info: &ProviderVerifyInfo) -> String {
    let mut lines = vec![
        format!("status: {}", info.status),
        format!("message: {}", info.message),
    ];
    if !info.sources.is_empty() {
        lines.push(String::new());
        lines.push("sources".to_string());
        for (key, value) in &info.sources {
            lines.push(format!("{key}: {value}"));
        }
    }
    lines.push(String::new());
    lines.push(format_provider_detail(&info.provider));
    lines.join("\n")
}

pub(crate) fn format_doctor_info(info: &Value) -> String {
    let mut lines = Vec::new();
    push_json_lines(&mut lines, None, info, 0);
    lines.join("\n")
}

fn push_json_lines(lines: &mut Vec<String>, key: Option<&str>, value: &Value, indent: usize) {
    let prefix = " ".repeat(indent);
    match value {
        Value::Object(map) => {
            if let Some(key) = key {
                lines.push(format!("{prefix}{key}:"));
            }
            for (child_key, child_value) in map {
                push_json_lines(lines, Some(child_key), child_value, indent + 2);
            }
        }
        Value::Array(items) => {
            if let Some(key) = key {
                lines.push(format!("{prefix}{key}:"));
            }
            if items.is_empty() {
                lines.push(format!("{prefix}  (none)"));
                return;
            }
            for item in items {
                match item {
                    Value::Object(_) | Value::Array(_) => {
                        lines.push(format!("{prefix}  -"));
                        push_json_lines(lines, None, item, indent + 4);
                    }
                    _ => lines.push(format!("{prefix}  - {}", scalar_to_string(item))),
                }
            }
        }
        _ => {
            let rendered = scalar_to_string(value);
            if let Some(key) = key {
                lines.push(format!("{prefix}{key}: {rendered}"));
            } else {
                lines.push(format!("{prefix}{rendered}"));
            }
        }
    }
}

fn scalar_to_string(value: &Value) -> String {
    match value {
        Value::Null => "null".to_string(),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        Value::String(value) => value.clone(),
        Value::Array(_) | Value::Object(_) => {
            unreachable!("composite value passed to scalar renderer")
        }
    }
}
