use super::super::{App, SubmitAction};

#[test]
fn goal_command_sets_pending_goal_mutation() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/goal set ship the terminal goal MVP"),
        SubmitAction::Handled
    ));

    assert_eq!(
        app.current_goal
            .as_ref()
            .map(|goal| goal.objective.as_str()),
        Some("ship the terminal goal MVP")
    );
    assert_eq!(
        app.pending_goal_mutation
            .as_ref()
            .and_then(|pending| pending.objective.as_deref()),
        Some("ship the terminal goal MVP")
    );
    assert_eq!(
        app.pending_goal_mutation
            .as_ref()
            .and_then(|pending| pending.status.as_deref()),
        Some("active")
    );
}

#[test]
fn goal_command_shorthand_sets_goal_and_runs_task() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/goal design a PK modeling roadmap"),
        SubmitAction::RunTask(task) if task == "design a PK modeling roadmap"
    ));

    assert_eq!(
        app.current_goal
            .as_ref()
            .map(|goal| goal.objective.as_str()),
        Some("design a PK modeling roadmap")
    );
    assert_eq!(app.last_submitted_task.as_deref(), Some("design a PK modeling roadmap"));
    assert_eq!(app.current_task.as_deref(), Some("design a PK modeling roadmap"));
    assert!(app.busy);
}

#[test]
fn goal_show_reports_local_goal_state() {
    let mut app = App::new();
    app.set_goal_selection("ship the terminal goal MVP".to_string());
    let _ = app.take_pending_history_lines();

    assert!(matches!(app.handle_command("/goal"), SubmitAction::Handled));

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("goal: ship the terminal goal MVP"));
    assert!(rendered.contains("goal_status: active"));
}

#[test]
fn session_hydration_updates_materialized_session_and_clears_pending_goal_mutation() {
    let mut app = App::new();
    app.set_goal_selection("queued local goal".to_string());

    app.apply_session_meta(crate::backend::BackendSessionMeta {
        session_id: "session-123".to_string(),
        command_mode: None,
        session_state: None,
        goal: Some(crate::backend::BackendGoal {
            objective: "queued local goal".to_string(),
            status: "active".to_string(),
        }),
    });

    assert_eq!(app.session_id, "session-123");
    assert_eq!(
        app.current_goal
            .as_ref()
            .map(|goal| goal.objective.as_str()),
        Some("queued local goal")
    );
    assert!(app.pending_goal_mutation.is_none());
}

#[test]
fn session_hydration_without_goal_does_not_clear_local_goal() {
    let mut app = App::new();
    app.set_goal_selection("keep local goal".to_string());
    app.pending_goal_mutation = None;

    app.apply_session_meta(crate::backend::BackendSessionMeta {
        session_id: "session-123".to_string(),
        command_mode: Some("chat".to_string()),
        session_state: Some("existing".to_string()),
        goal: None,
    });

    assert_eq!(
        app.current_goal
            .as_ref()
            .map(|goal| goal.objective.as_str()),
        Some("keep local goal")
    );
}
