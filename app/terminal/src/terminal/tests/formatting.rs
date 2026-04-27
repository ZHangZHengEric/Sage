use serde_json::json;

use crate::backend::ConfigInitInfo;
use crate::terminal_support::{format_config_init, format_doctor_info};

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
