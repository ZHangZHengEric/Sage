use super::{help::usage_text, parse_startup_action, StartupBehavior};
use crate::app::{SessionPickerMode, SubmitAction};
use crate::display_policy::DisplayMode;

#[test]
fn parse_startup_action_defaults_to_plain_tui() {
    assert!(parse_startup_action(Vec::<String>::new())
        .expect("parse")
        .matches_run_none());
}

#[test]
fn parse_startup_action_supports_resume_picker() {
    let action = parse_startup_action(vec!["resume".to_string()]).expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run {
            action: Some(SubmitAction::OpenSessionPicker {
                mode: SessionPickerMode::Resume,
                limit: 10
            }),
            ..
        }
    ));
}

#[test]
fn parse_startup_action_supports_run_and_chat_prompts() {
    let run_action = parse_startup_action(vec![
        "run".to_string(),
        "inspect".to_string(),
        "repo".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        run_action,
        StartupBehavior::Run { action: Some(SubmitAction::RunTask(prompt)), .. }
            if prompt == "inspect repo"
    ));

    let chat_action =
        parse_startup_action(vec!["chat".to_string(), "hello".to_string()]).expect("parse");
    assert!(matches!(
        chat_action,
        StartupBehavior::Run { action: Some(SubmitAction::RunTask(prompt)), .. }
            if prompt == "hello"
    ));
}

#[test]
fn parse_startup_action_supports_agent_config_option() {
    let action = parse_startup_action(vec![
        "--agent-config".to_string(),
        "examples/coding_agent_config.json".to_string(),
        "chat".to_string(),
        "hello".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run {
            action: Some(SubmitAction::RunTask(prompt)),
            options,
        } if prompt == "hello"
            && options.agent_config.as_deref()
                == Some("examples/coding_agent_config.json")
    ));
}

#[test]
fn parse_startup_action_supports_coding_shortcut() {
    let action = parse_startup_action(vec![
        "coding".to_string(),
        "--workspace".to_string(),
        "/tmp/demo-workspace".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run { action: None, options }
            if options.agent_config.as_deref() == Some("coding")
            && options.agent_id.is_none()
            && options.workspace.as_deref() == Some("/tmp/demo-workspace")
    ));
}

#[test]
fn parse_startup_action_supports_coding_shortcut_prompt() {
    let action = parse_startup_action(vec![
        "--agent-id".to_string(),
        "agent_demo".to_string(),
        "coding".to_string(),
        "--workspace".to_string(),
        "/tmp/demo-workspace".to_string(),
        "inspect".to_string(),
        "repo".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run { action: Some(SubmitAction::RunTask(prompt)), options }
            if prompt == "inspect repo"
            && options.agent_config.as_deref() == Some("coding")
            && options.agent_id.is_none()
            && options.workspace.as_deref() == Some("/tmp/demo-workspace")
    ));
}

#[test]
fn parse_startup_action_normalizes_agent_id_option() {
    let action = parse_startup_action(vec![
        "--agent-id".to_string(),
        "  agent_demo  ".to_string(),
        "chat".to_string(),
        "hello".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run { options, .. }
            if options.agent_id.as_deref() == Some("agent_demo")
    ));
}

#[test]
fn parse_startup_action_normalizes_agent_config_value() {
    let action = parse_startup_action(vec![
        "--agent-config".to_string(),
        "\"/tmp/My Project/coding agent.json\"".to_string(),
        "chat".to_string(),
        "hello".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run { options, .. }
            if options.agent_config.as_deref() == Some("/tmp/My Project/coding agent.json")
    ));
}

#[test]
fn parse_startup_action_supports_doctor() {
    let action = parse_startup_action(vec!["doctor".to_string()]).expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run {
            action: Some(SubmitAction::ShowDoctor {
                probe_provider: false
            }),
            ..
        }
    ));

    let action = parse_startup_action(vec!["doctor".to_string(), "probe-provider".to_string()])
        .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run {
            action: Some(SubmitAction::ShowDoctor {
                probe_provider: true
            }),
            ..
        }
    ));

    let action = parse_startup_action(vec!["doctor".to_string(), "--probe-provider".to_string()])
        .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run {
            action: Some(SubmitAction::ShowDoctor {
                probe_provider: true
            }),
            ..
        }
    ));
}

#[test]
fn parse_startup_action_supports_config_init() {
    let action =
        parse_startup_action(vec!["config".to_string(), "init".to_string()]).expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run {
            action: Some(SubmitAction::InitConfig {
                path: None,
                force: false
            }),
            ..
        }
    ));

    let action = parse_startup_action(vec![
        "config".to_string(),
        "init".to_string(),
        "/tmp/demo.env".to_string(),
        "--force".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run { action: Some(SubmitAction::InitConfig {
            path: Some(path),
            force: true
        }), .. } if path == "/tmp/demo.env"
    ));
}

#[test]
fn parse_startup_action_supports_provider_verify() {
    let action = parse_startup_action(vec![
        "provider".to_string(),
        "verify".to_string(),
        "name=demo".to_string(),
        "model=demo-chat".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run { action: Some(SubmitAction::VerifyProvider(fields)), .. }
            if fields == vec!["name=demo".to_string(), "model=demo-chat".to_string()]
    ));
}

#[test]
fn parse_startup_action_supports_sessions_picker() {
    let action = parse_startup_action(vec!["sessions".to_string()]).expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run {
            action: Some(SubmitAction::OpenSessionPicker {
                mode: SessionPickerMode::Browse,
                limit: 10
            }),
            ..
        }
    ));

    let action =
        parse_startup_action(vec!["sessions".to_string(), "25".to_string()]).expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run {
            action: Some(SubmitAction::OpenSessionPicker {
                mode: SessionPickerMode::Browse,
                limit: 25
            }),
            ..
        }
    ));
}

#[test]
fn parse_startup_action_supports_sessions_inspect() {
    let latest = parse_startup_action(vec![
        "sessions".to_string(),
        "inspect".to_string(),
        "latest".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        latest,
        StartupBehavior::Run { action: Some(SubmitAction::ShowSession(session_id)), .. }
            if session_id == "latest"
    ));

    let specific = parse_startup_action(vec![
        "sessions".to_string(),
        "inspect".to_string(),
        "local-000123".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        specific,
        StartupBehavior::Run { action: Some(SubmitAction::ShowSession(session_id)), .. }
            if session_id == "local-000123"
    ));
}

#[test]
fn parse_startup_action_supports_resume_targets() {
    let latest =
        parse_startup_action(vec!["resume".to_string(), "latest".to_string()]).expect("parse");
    assert!(matches!(
        latest,
        StartupBehavior::Run {
            action: Some(SubmitAction::ResumeLatest),
            ..
        }
    ));

    let specific = parse_startup_action(vec!["resume".to_string(), "local-000123".to_string()])
        .expect("parse");
    assert!(matches!(
        specific,
        StartupBehavior::Run { action: Some(SubmitAction::ResumeSession(session_id)), .. }
            if session_id == "local-000123"
    ));
}

#[test]
fn parse_startup_action_supports_agent_options() {
    let action = parse_startup_action(vec![
        "--agent-id".to_string(),
        "agent_demo".to_string(),
        "--agent-mode".to_string(),
        "fibre".to_string(),
        "--display".to_string(),
        "verbose".to_string(),
        "run".to_string(),
        "inspect".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run { action: Some(SubmitAction::RunTask(prompt)), options }
            if prompt == "inspect"
            && options.agent_id.as_deref() == Some("agent_demo")
            && options.agent_mode.as_deref() == Some("fibre")
            && options.display_mode == Some(DisplayMode::Verbose)
            && options.workspace.is_none()
    ));
}

#[test]
fn parse_startup_action_supports_workspace_option() {
    let action = parse_startup_action(vec![
        "--workspace".to_string(),
        "/tmp/demo-workspace".to_string(),
        "run".to_string(),
        "inspect".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run { action: Some(SubmitAction::RunTask(prompt)), options }
            if prompt == "inspect"
            && options.workspace.as_deref() == Some("/tmp/demo-workspace")
    ));
}

#[test]
fn parse_startup_action_supports_sandbox_type_option() {
    let action = parse_startup_action(vec![
        "--sandbox-type".to_string(),
        "LOCAL".to_string(),
        "run".to_string(),
        "inspect".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run { action: Some(SubmitAction::RunTask(prompt)), options }
            if prompt == "inspect"
            && options.sandbox_type.as_deref() == Some("local")
    ));
}

#[test]
fn parse_startup_action_supports_display_option() {
    let action = parse_startup_action(vec![
        "--display".to_string(),
        "compact".to_string(),
        "run".to_string(),
        "inspect".to_string(),
    ])
    .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run { action: Some(SubmitAction::RunTask(prompt)), options }
            if prompt == "inspect"
            && options.display_mode == Some(DisplayMode::Compact)
    ));
}

#[test]
fn startup_options_merge_drops_agent_fallbacks_when_config_present() {
    let merged = super::StartupOptions {
        agent_id: None,
        agent_config: None,
        agent_mode: None,
        display_mode: None,
        workspace: None,
        sandbox_type: None,
        sandbox_approval_mode: None,
    }
    .with_fallbacks(super::StartupOptions {
        agent_id: Some("agent_demo".to_string()),
        agent_config: Some("/tmp/coding_config.json".to_string()),
        agent_mode: Some("multi".to_string()),
        display_mode: Some(DisplayMode::Verbose),
        workspace: Some("/tmp/demo-workspace".to_string()),
        sandbox_type: Some("local".to_string()),
        sandbox_approval_mode: Some("untrusted".to_string()),
    });

    assert_eq!(merged.agent_id.as_deref(), None);
    assert_eq!(
        merged.agent_config.as_deref(),
        Some("/tmp/coding_config.json")
    );
    assert_eq!(merged.agent_mode, None);
    assert_eq!(merged.display_mode, Some(DisplayMode::Verbose));
    assert_eq!(merged.workspace.as_deref(), Some("/tmp/demo-workspace"));
    assert_eq!(merged.sandbox_type.as_deref(), Some("local"));
    assert_eq!(merged.sandbox_approval_mode.as_deref(), Some("untrusted"));
}

#[test]
fn startup_options_merge_uses_agent_fallbacks_without_config() {
    let merged = super::StartupOptions {
        agent_id: None,
        agent_config: None,
        agent_mode: Some("fibre".to_string()),
        display_mode: None,
        workspace: None,
        sandbox_type: Some("remote".to_string()),
        sandbox_approval_mode: Some("never".to_string()),
    }
    .with_fallbacks(super::StartupOptions {
        agent_id: Some("agent_demo".to_string()),
        agent_config: None,
        agent_mode: Some("multi".to_string()),
        display_mode: Some(DisplayMode::Verbose),
        workspace: Some("/tmp/demo-workspace".to_string()),
        sandbox_type: Some("local".to_string()),
        sandbox_approval_mode: Some("untrusted".to_string()),
    });

    assert_eq!(merged.agent_id.as_deref(), Some("agent_demo"));
    assert_eq!(merged.agent_config, None);
    assert_eq!(merged.agent_mode.as_deref(), Some("fibre"));
    assert_eq!(merged.display_mode, Some(DisplayMode::Verbose));
    assert_eq!(merged.workspace.as_deref(), Some("/tmp/demo-workspace"));
    assert_eq!(merged.sandbox_type.as_deref(), Some("remote"));
    assert_eq!(merged.sandbox_approval_mode.as_deref(), Some("never"));
}

#[test]
fn startup_options_merge_keeps_explicit_mode_with_config() {
    let merged = super::StartupOptions {
        agent_id: Some("agent_demo".to_string()),
        agent_config: Some("/tmp/coding_config.json".to_string()),
        agent_mode: Some("multi".to_string()),
        display_mode: None,
        workspace: None,
        sandbox_type: None,
        sandbox_approval_mode: None,
    }
    .with_fallbacks(super::StartupOptions {
        agent_id: Some("persisted_agent".to_string()),
        agent_config: None,
        agent_mode: Some("fibre".to_string()),
        display_mode: Some(DisplayMode::Verbose),
        workspace: Some("/tmp/demo-workspace".to_string()),
        sandbox_type: Some("passthrough".to_string()),
        sandbox_approval_mode: Some("untrusted".to_string()),
    });

    assert_eq!(merged.agent_id, None);
    assert_eq!(
        merged.agent_config.as_deref(),
        Some("/tmp/coding_config.json")
    );
    assert_eq!(merged.agent_mode.as_deref(), Some("multi"));
    assert_eq!(merged.display_mode, Some(DisplayMode::Verbose));
    assert_eq!(merged.workspace.as_deref(), Some("/tmp/demo-workspace"));
    assert_eq!(merged.sandbox_type.as_deref(), Some("passthrough"));
    assert_eq!(merged.sandbox_approval_mode.as_deref(), Some("untrusted"));
}

#[test]
fn parse_startup_action_rejects_invalid_agent_mode() {
    let err = parse_startup_action(vec!["--agent-mode".to_string(), "weird".to_string()])
        .expect_err("should fail");
    assert!(err.to_string().contains("simple, multi, fibre"));
}

#[test]
fn parse_startup_action_rejects_blank_agent_id() {
    let err = parse_startup_action(vec!["--agent-id".to_string(), "   ".to_string()])
        .expect_err("should fail");
    assert!(err.to_string().contains("non-empty"));
}

#[test]
fn parse_startup_action_rejects_blank_agent_config() {
    let err = parse_startup_action(vec!["--agent-config".to_string(), "   ".to_string()])
        .expect_err("should fail");
    assert!(err.to_string().contains("non-empty"));
}

#[test]
fn parse_startup_action_rejects_invalid_display_mode() {
    let err = parse_startup_action(vec!["--display".to_string(), "loud".to_string()])
        .expect_err("should fail");
    assert!(err.to_string().contains("compact, verbose"));
}

#[test]
fn parse_startup_action_rejects_invalid_sandbox_type() {
    let err = parse_startup_action(vec!["--sandbox-type".to_string(), "unsafe".to_string()])
        .expect_err("should fail");
    assert!(err.to_string().contains("local, remote, passthrough"));
}

#[test]
fn parse_startup_action_rejects_unknown_commands() {
    let err = parse_startup_action(vec!["unknown".to_string()]).expect_err("should fail");
    assert!(err.to_string().contains("unsupported arguments"));
}

#[test]
fn parse_startup_action_rejects_invalid_sessions_limit() {
    let err = parse_startup_action(vec!["sessions".to_string(), "0".to_string()])
        .expect_err("should fail");
    assert!(err.to_string().contains("positive integer"));
}

#[test]
fn parse_startup_action_rejects_missing_run_prompt() {
    let err = parse_startup_action(vec!["run".to_string()]).expect_err("should fail");
    assert!(err.to_string().contains("requires a prompt"));
}

#[test]
fn parse_startup_action_supports_help_flag() {
    let action = parse_startup_action(vec!["--help".to_string()]).expect("parse");
    assert!(matches!(action, StartupBehavior::PrintHelp));
}

#[test]
fn startup_usage_shows_public_sage_tui_entrypoint() {
    let usage = usage_text();
    assert!(usage.contains("sage tui"));
    assert!(!usage.contains("sage-terminal"));
}

impl StartupBehavior {
    fn matches_run_none(&self) -> bool {
        matches!(self, StartupBehavior::Run { action: None, .. })
    }
}
