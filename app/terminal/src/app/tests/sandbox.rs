use super::super::{App, SubmitAction};
use crate::backend::SandboxApprovalRequest;

#[test]
fn sandbox_command_sets_override_and_requests_restart() {
    let mut app = App::new();
    let _ = app.take_backend_restart_request();

    assert!(matches!(
        app.handle_command("/sandbox set local"),
        SubmitAction::Handled
    ));

    assert_eq!(app.sandbox_type.as_deref(), Some("local"));
    assert!(app.take_backend_restart_request());
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("sandbox type set: local"));
}

#[test]
fn sandbox_show_reports_current_override() {
    let mut app = App::new();
    app.set_sandbox_type_selection("remote".to_string());
    app.set_sandbox_approval_mode_selection("untrusted".to_string());
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/sandbox show"),
        SubmitAction::Handled
    ));

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("sandbox: remote (session override)"));
    assert!(rendered.contains("approval_mode: untrusted"));
    assert!(rendered.contains("workspace: "));
    assert!(rendered.contains("restart: pending"));
    assert!(rendered.contains("filesystem: remote workspace"));
    assert!(rendered.contains("next: run /doctor"));
    assert!(!rendered.contains("sandbox_type:"));
}

#[test]
fn sandbox_approval_command_sets_mode_and_requests_restart() {
    let mut app = App::new();
    let _ = app.take_backend_restart_request();

    assert!(matches!(
        app.handle_command("/sandbox approval set never"),
        SubmitAction::Handled
    ));

    assert_eq!(app.sandbox_approval_mode, "never");
    assert!(app.take_backend_restart_request());
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("sandbox approval mode set: never"));
}

#[test]
fn sandbox_approval_command_accepts_codex_alias() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/sandbox approval set unless-trusted"),
        SubmitAction::Handled
    ));

    assert_eq!(app.sandbox_approval_mode, "untrusted");
}

#[test]
fn sandbox_clear_removes_override() {
    let mut app = App::new();
    app.set_sandbox_type_selection("passthrough".to_string());
    let _ = app.take_backend_restart_request();

    assert!(matches!(
        app.handle_command("/sandbox clear"),
        SubmitAction::Handled
    ));

    assert_eq!(app.sandbox_type, None);
    assert!(app.take_backend_restart_request());
}

#[test]
fn sandbox_approval_request_sets_pending_status() {
    let mut app = App::new();
    app.apply_sandbox_approval_request(SandboxApprovalRequest {
        command: "git push origin main".to_string(),
        approval_id: "shapproval_demo".to_string(),
        command_hash: Some("hash_demo".to_string()),
        category: Some("git-push".to_string()),
        reason: Some("git push changes remote state".to_string()),
        approval_mode: Some("on-request".to_string()),
        hint: Some("Ask the user for confirmation.".to_string()),
    });

    assert_eq!(
        app.pending_sandbox_approval
            .as_ref()
            .map(|request| request.approval_id.as_str()),
        Some("shapproval_demo")
    );
    assert!(app.status.contains("approval required"));
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("sandbox approval required"));
    assert!(rendered.contains("approval_mode: on-request"));
    assert!(rendered.contains("command_hash: hash_demo"));
    assert!(rendered.contains("Use /approve to run it once"));
}

#[test]
fn status_command_reports_pending_sandbox_approval_details() {
    let mut app = App::new();
    app.apply_sandbox_approval_request(SandboxApprovalRequest {
        command: "git push origin main".to_string(),
        approval_id: "shapproval_demo".to_string(),
        command_hash: Some("hash_demo".to_string()),
        category: Some("git-push".to_string()),
        reason: Some("git push changes remote state".to_string()),
        approval_mode: Some("on-request".to_string()),
        hint: None,
    });
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/status"),
        SubmitAction::Handled
    ));

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("sandbox approval: pending shapproval_demo"));
    assert!(rendered.contains("approval command: git push origin main"));
    assert!(rendered.contains("approval category: git-push"));
    assert!(rendered.contains("approval mode: on-request"));
    assert!(rendered.contains("approval hash: hash_demo"));
}

#[test]
fn approve_command_routes_to_backend_decision_action() {
    let mut app = App::new();
    app.apply_sandbox_approval_request(SandboxApprovalRequest {
        command: "git push origin main".to_string(),
        approval_id: "shapproval_demo".to_string(),
        command_hash: Some("hash_demo".to_string()),
        category: None,
        reason: None,
        approval_mode: None,
        hint: None,
    });

    let action = app.handle_command("/approve");

    assert!(matches!(action, SubmitAction::ApproveSandboxCommand));
    assert!(app.pending_sandbox_approval.is_some());
    app.clear_pending_sandbox_approval();
    assert!(app.pending_sandbox_approval.is_none());
}

#[test]
fn deny_command_clears_pending_approval() {
    let mut app = App::new();
    app.apply_sandbox_approval_request(SandboxApprovalRequest {
        command: "git push origin main".to_string(),
        approval_id: "shapproval_demo".to_string(),
        command_hash: Some("hash_demo".to_string()),
        category: None,
        reason: None,
        approval_mode: None,
        hint: None,
    });

    assert!(matches!(
        app.handle_command("/deny"),
        SubmitAction::DenySandboxCommand
    ));
    assert!(app.deny_pending_sandbox_approval());
    assert!(app.pending_sandbox_approval.is_none());
}
