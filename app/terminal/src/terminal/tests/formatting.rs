use serde_json::json;

use crate::backend::{ConfigInitInfo, SkillInfo};
use crate::terminal_support::{format_config_init, format_doctor_info, format_skills_list};

#[test]
fn format_doctor_info_renders_nested_objects_and_lists() {
    let info = json!({
        "status": "ok",
        "warnings": [],
        "dependencies": {
            "dotenv": true
        }
    });

    let rendered = format_doctor_info(&info);
    assert!(rendered.contains("status: ok"));
    assert!(rendered.contains("warnings:"));
    assert!(rendered.contains("(none)"));
    assert!(rendered.contains("dependencies:"));
    assert!(rendered.contains("dotenv: true"));
}

#[test]
fn format_config_init_renders_next_steps() {
    let rendered = format_config_init(&ConfigInitInfo {
        path: "/tmp/.sage_env".to_string(),
        template: "minimal".to_string(),
        overwritten: true,
        next_steps: vec!["export SAGE_DB_TYPE=file".to_string()],
    });

    assert!(rendered.contains("config initialized"));
    assert!(rendered.contains("path: /tmp/.sage_env"));
    assert!(rendered.contains("template: minimal"));
    assert!(rendered.contains("overwritten: true"));
    assert!(rendered.contains("- export SAGE_DB_TYPE=file"));
}

#[test]
fn format_skills_list_uses_compact_descriptions() {
    let rendered = format_skills_list(
        &[SkillInfo {
            name: "agent-browser".to_string(),
            source: "system".to_string(),
            description: "Browser automation CLI for AI agents. Use when the user needs to interact with websites, including navigating pages, filling forms, clicking buttons, taking screenshots, extracting data, testing web apps, or automating any browser task.".to_string(),
        }],
        &["agent-browser".to_string()],
    );

    assert!(rendered.contains("active skills: agent-browser"));
    assert!(rendered.contains("visible skills: 1"));
    assert!(rendered.contains("agent-browser  [system]"));
    assert!(rendered.contains("Browser automation CLI for AI agents."));
    assert!(!rendered.contains("automating any browser task"));
    assert!(rendered.contains("type /skill add for searchable previews"));
}
