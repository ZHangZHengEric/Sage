use super::super::{App, SubmitAction};
use crate::backend::{SandboxApprovalRequest, SandboxApprovalResolution};

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
fn approvals_command_reports_recent_sandbox_approval_history() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/approvals"),
        SubmitAction::Handled
    ));
    let empty = app
        .take_pending_history_lines()
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(empty.contains("sandbox approvals: none"));

    app.apply_sandbox_approval_request(SandboxApprovalRequest {
        command: "git push origin main".to_string(),
        approval_id: "shapproval_demo".to_string(),
        command_hash: Some("hash_demo_123456789".to_string()),
        category: Some("git-push".to_string()),
        reason: None,
        approval_mode: Some("on-request".to_string()),
        hint: None,
    });
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/approvals"),
        SubmitAction::Handled
    ));
    let pending = app
        .take_pending_history_lines()
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(pending.contains("sandbox approvals"));
    assert!(pending.contains("pending  shapproval_demo"));
    assert!(pending.contains("git push origin main"));
    assert!(pending.contains("category: git-push"));
    assert!(pending.contains("#hash_demo_12"));

    app.apply_sandbox_approval_resolution(SandboxApprovalResolution {
        approval_id: "shapproval_demo".to_string(),
        status: "approved".to_string(),
        decision: Some("approve".to_string()),
        command: Some("git push origin main".to_string()),
        command_hash: Some("hash_demo_123456789".to_string()),
        category: Some("git-push".to_string()),
    });
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/approvals"),
        SubmitAction::Handled
    ));
    let resolved = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(resolved.contains("approved  shapproval_demo"));
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
fn sandbox_approval_resolution_clears_matching_pending_request() {
    let mut app = App::new();
    app.apply_sandbox_approval_request(SandboxApprovalRequest {
        command: "git push origin main".to_string(),
        approval_id: "shapproval_demo".to_string(),
        command_hash: Some("hash_demo_123456789".to_string()),
        category: Some("git-push".to_string()),
        reason: None,
        approval_mode: Some("on-request".to_string()),
        hint: None,
    });
    let _ = app.take_pending_history_lines();

    app.apply_sandbox_approval_resolution(SandboxApprovalResolution {
        approval_id: "shapproval_demo".to_string(),
        status: "approved".to_string(),
        decision: Some("approve".to_string()),
        command: Some("git push origin main".to_string()),
        command_hash: Some("hash_demo_123456789".to_string()),
        category: Some("git-push".to_string()),
    });

    assert!(app.pending_sandbox_approval.is_none());
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("sandbox approval approved"));
    assert!(rendered.contains("approval_id: shapproval_demo"));
    assert!(rendered.contains("command_hash: hash_demo_12"));
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

fn rendered_history(app: &App) -> String {
    app.pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn runtime_command_switches_backend_runtime_and_requests_restart() {
    let mut app = App::new();
    let _ = app.take_backend_restart_request();
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/runtime set v2"),
        SubmitAction::Handled
    ));
    assert_eq!(app.runtime, crate::backend::BackendRuntime::V2);
    assert!(app.take_backend_restart_request());
    assert!(rendered_history(&app).contains("runtime set: v2"));

    let _ = app.take_pending_history_lines();
    assert!(matches!(
        app.handle_command("/runtime set v3"),
        SubmitAction::Handled
    ));
    assert_eq!(app.runtime, crate::backend::BackendRuntime::V2);
    assert!(rendered_history(&app).contains("runtime must be one of: v1, v2"));

    let _ = app.take_pending_history_lines();
    assert!(matches!(
        app.handle_command("/status"),
        SubmitAction::Handled
    ));
    assert!(rendered_history(&app).contains("runtime: v2"));

    assert!(matches!(
        app.handle_command("/remember"),
        SubmitAction::RememberSandboxCommand
    ));
}

#[test]
fn v2_session_is_only_known_after_the_backend_announces_it() {
    let mut app = App::new();
    app.set_runtime_selection(crate::backend::BackendRuntime::V2);
    assert!(!app.v2_session_known);

    app.apply_session_meta(crate::backend::BackendSessionMeta {
        session_id: "session_v2".to_string(),
        command_mode: Some("chat".to_string()),
        session_state: Some("active".to_string()),
        goal: None,
    });
    assert!(app.v2_session_known);
    assert_eq!(app.session_id, "session_v2");

    app.reset_session();
    assert!(!app.v2_session_known);
    assert!(app.pending_v2_input.is_none());
}

#[test]
fn resuming_a_v2_session_marks_it_known_and_restarts_the_backend() {
    let mut app = App::new();
    app.set_runtime_selection(crate::backend::BackendRuntime::V2);
    let _ = app.take_backend_restart_request();

    app.load_resumed_session(
        "session_v2".to_string(),
        vec![(
            crate::app::MessageKind::User,
            "create hello.txt".to_string(),
        )],
    );

    assert_eq!(app.session_id, "session_v2");
    assert!(app.v2_session_known);
    assert!(app.take_backend_restart_request());

    let mut legacy = App::new();
    legacy.load_resumed_session("local-000123".to_string(), Vec::new());
    assert!(!legacy.v2_session_known);
}

#[test]
fn v2_input_while_busy_becomes_a_steer_instead_of_a_new_task() {
    let mut app = App::new();
    app.set_runtime_selection(crate::backend::BackendRuntime::V2);
    app.input = "first task".to_string();
    app.input_cursor = app.input.len();
    assert!(matches!(app.submit_input(), SubmitAction::RunTask(_)));
    assert!(app.busy);
    let _ = app.take_pending_history_lines();

    app.input = "also update the tests".to_string();
    app.input_cursor = app.input.len();
    let action = app.submit_input();

    assert!(matches!(action, SubmitAction::SteerTask(text) if text == "also update the tests"));
    // 仍是同一个任务在跑：不重置计时、不覆盖 current_task。
    assert!(app.busy);
    assert_eq!(app.current_task.as_deref(), Some("first task"));
    assert_eq!(app.last_submitted_task.as_deref(), Some("first task"));
    assert!(rendered_history(&app).contains("also update the tests"));
    assert_eq!(
        app.input_history.last().map(String::as_str),
        Some("also update the tests")
    );
    assert!(app.status.starts_with("steering"));
    assert!(app.input.is_empty());
}

#[test]
fn v2_steer_is_refused_while_an_approval_is_pending() {
    let mut app = App::new();
    app.set_runtime_selection(crate::backend::BackendRuntime::V2);
    app.begin_task_submission("first task".to_string(), true);
    app.pending_sandbox_approval = Some(SandboxApprovalRequest {
        command: "file_write hello.txt".to_string(),
        approval_id: "interaction_1".to_string(),
        command_hash: None,
        category: Some("write".to_string()),
        reason: None,
        approval_mode: None,
        hint: Some("/approve once · /deny".to_string()),
    });
    let _ = app.take_pending_history_lines();

    app.input = "also update the tests".to_string();
    app.input_cursor = app.input.len();
    let action = app.submit_input();

    assert!(matches!(action, SubmitAction::Handled));
    assert!(rendered_history(&app).contains("answer the pending approval first"));
    assert!(app.status.starts_with("approval required"));
}

#[test]
fn v1_input_while_busy_is_still_submitted_as_a_task() {
    let mut app = App::new();
    app.begin_task_submission("first task".to_string(), true);

    app.input = "next prompt".to_string();
    app.input_cursor = app.input.len();

    assert!(matches!(app.submit_input(), SubmitAction::RunTask(text) if text == "next prompt"));
    assert_eq!(app.current_task.as_deref(), Some("next prompt"));
}

#[test]
fn v2_input_request_is_shown_and_kept_pending() {
    let mut app = App::new();
    let _ = app.take_pending_history_lines();
    app.apply_v2_input_request(crate::backend::V2InputRequest {
        interaction_id: "interaction_q".to_string(),
        interaction_type: "user_input".to_string(),
        prompt: "Which target should I use?".to_string(),
        allowed_decisions: vec!["submit".to_string(), "cancel".to_string()],
    });

    let rendered = rendered_history(&app);
    assert!(rendered.contains("user_input required"));
    assert!(rendered.contains("Which target should I use?"));
    assert!(rendered.contains("Type your answer in the composer"));
    assert_eq!(
        app.pending_v2_input
            .as_ref()
            .map(|value| value.interaction_id.as_str()),
        Some("interaction_q")
    );
    assert!(app.status.starts_with("input required"));
}
