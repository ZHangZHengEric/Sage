use super::{parse_startup_action, StartupBehavior};
use crate::app::{SessionPickerMode, SubmitAction};

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
        StartupBehavior::Run(Some(SubmitAction::OpenSessionPicker {
            mode: SessionPickerMode::Resume,
            limit: 10
        }))
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
        StartupBehavior::Run(Some(SubmitAction::RunTask(prompt)))
            if prompt == "inspect repo"
    ));

    let chat_action =
        parse_startup_action(vec!["chat".to_string(), "hello".to_string()]).expect("parse");
    assert!(matches!(
        chat_action,
        StartupBehavior::Run(Some(SubmitAction::RunTask(prompt)))
            if prompt == "hello"
    ));
}

#[test]
fn parse_startup_action_supports_doctor() {
    let action = parse_startup_action(vec!["doctor".to_string()]).expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run(Some(SubmitAction::ShowDoctor {
            probe_provider: false
        }))
    ));

    let action = parse_startup_action(vec!["doctor".to_string(), "probe-provider".to_string()])
        .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run(Some(SubmitAction::ShowDoctor {
            probe_provider: true
        }))
    ));

    let action = parse_startup_action(vec!["doctor".to_string(), "--probe-provider".to_string()])
        .expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run(Some(SubmitAction::ShowDoctor {
            probe_provider: true
        }))
    ));
}

#[test]
fn parse_startup_action_supports_config_init() {
    let action =
        parse_startup_action(vec!["config".to_string(), "init".to_string()]).expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run(Some(SubmitAction::InitConfig {
            path: None,
            force: false
        }))
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
        StartupBehavior::Run(Some(SubmitAction::InitConfig {
            path: Some(path),
            force: true
        })) if path == "/tmp/demo.env"
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
        StartupBehavior::Run(Some(SubmitAction::VerifyProvider(fields)))
            if fields == vec!["name=demo".to_string(), "model=demo-chat".to_string()]
    ));
}

#[test]
fn parse_startup_action_supports_sessions_picker() {
    let action = parse_startup_action(vec!["sessions".to_string()]).expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run(Some(SubmitAction::OpenSessionPicker {
            mode: SessionPickerMode::Browse,
            limit: 10
        }))
    ));

    let action =
        parse_startup_action(vec!["sessions".to_string(), "25".to_string()]).expect("parse");
    assert!(matches!(
        action,
        StartupBehavior::Run(Some(SubmitAction::OpenSessionPicker {
            mode: SessionPickerMode::Browse,
            limit: 25
        }))
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
        StartupBehavior::Run(Some(SubmitAction::ShowSession(session_id)))
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
        StartupBehavior::Run(Some(SubmitAction::ShowSession(session_id)))
            if session_id == "local-000123"
    ));
}

#[test]
fn parse_startup_action_supports_resume_targets() {
    let latest =
        parse_startup_action(vec!["resume".to_string(), "latest".to_string()]).expect("parse");
    assert!(matches!(
        latest,
        StartupBehavior::Run(Some(SubmitAction::ResumeLatest))
    ));

    let specific = parse_startup_action(vec!["resume".to_string(), "local-000123".to_string()])
        .expect("parse");
    assert!(matches!(
        specific,
        StartupBehavior::Run(Some(SubmitAction::ResumeSession(session_id)))
            if session_id == "local-000123"
    ));
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

impl StartupBehavior {
    fn matches_run_none(&self) -> bool {
        matches!(self, StartupBehavior::Run(None))
    }
}
