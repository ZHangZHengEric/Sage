use super::super::{App, SubmitAction};

#[test]
fn goal_command_sets_pending_goal_mutation() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/goal set ship the runtime goal contract"),
        SubmitAction::Handled
    ));

    assert_eq!(
        app.current_goal
            .as_ref()
            .map(|goal| goal.objective.as_str()),
        Some("ship the runtime goal contract")
    );
    assert_eq!(
        app.pending_goal_mutation
            .as_ref()
            .and_then(|pending| pending.objective.as_deref()),
        Some("ship the runtime goal contract")
    );
    assert_eq!(
        app.pending_goal_mutation
            .as_ref()
            .and_then(|pending| pending.status.as_deref()),
        Some("active")
    );
}

#[test]
fn goal_command_shorthand_sets_pending_goal_mutation() {
    let mut app = App::new();

    assert!(matches!(
        app.handle_command("/goal ship the runtime goal contract"),
        SubmitAction::RunTask(task) if task == "ship the runtime goal contract"
    ));

    assert_eq!(
        app.current_goal
            .as_ref()
            .map(|goal| goal.objective.as_str()),
        Some("ship the runtime goal contract")
    );
    assert_eq!(
        app.pending_goal_mutation
            .as_ref()
            .and_then(|pending| pending.objective.as_deref()),
        Some("ship the runtime goal contract")
    );
    assert_eq!(
        app.pending_goal_mutation
            .as_ref()
            .and_then(|pending| pending.status.as_deref()),
        Some("active")
    );
    assert_eq!(app.last_submitted_task.as_deref(), Some("ship the runtime goal contract"));
    assert_eq!(app.current_task.as_deref(), Some("ship the runtime goal contract"));
    assert!(app.busy);
}

#[test]
fn goal_show_reports_current_goal() {
    let mut app = App::new();
    app.set_goal_selection("ship the runtime goal contract".to_string());
    let _ = app.take_pending_history_lines();

    assert!(matches!(
        app.handle_command("/goal show"),
        SubmitAction::Handled
    ));

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("goal: ship the runtime goal contract"));
    assert!(rendered.contains("goal_status: active"));
}

#[test]
fn session_hydration_applies_goal_and_clears_pending_mutation() {
    let mut app = App::new();
    app.set_goal_selection("queued local goal".to_string());

    app.apply_session_meta(crate::backend::BackendSessionMeta {
        session_id: "session-123".to_string(),
        command_mode: None,
        session_state: None,
        goal: Some(crate::backend::BackendGoal {
            objective: "hydrated goal".to_string(),
            status: "paused".to_string(),
        }),
        goal_transition: None,
    });

    assert_eq!(app.session_id, "session-123");
    assert_eq!(
        app.current_goal
            .as_ref()
            .map(|goal| goal.objective.as_str()),
        Some("hydrated goal")
    );
    assert_eq!(
        app.current_goal.as_ref().map(|goal| goal.status.as_str()),
        Some("paused")
    );
    assert!(app.pending_goal_mutation.is_none());
}

#[test]
fn resume_hydration_announces_continuing_goal() {
    let mut app = App::new();
    let _ = app.take_pending_history_lines();

    app.apply_session_meta(crate::backend::BackendSessionMeta {
        session_id: "session-resume".to_string(),
        command_mode: Some("resume".to_string()),
        session_state: Some("existing".to_string()),
        goal: Some(crate::backend::BackendGoal {
            objective: "continue shipping".to_string(),
            status: "active".to_string(),
        }),
        goal_transition: Some(crate::backend::BackendGoalTransition {
            transition_type: "resumed".to_string(),
            objective: Some("continue shipping".to_string()),
            status: Some("active".to_string()),
            previous_objective: None,
            previous_status: None,
        }),
    });

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("continuing goal"));
    assert!(rendered.contains("continue shipping"));
    assert_eq!(app.status, "resumed  session-resume");
}

#[test]
fn hydration_announces_goal_completion_transition() {
    let mut app = App::new();
    app.current_goal = Some(crate::backend::BackendGoal {
        objective: "finish contract".to_string(),
        status: "active".to_string(),
    });
    let _ = app.take_pending_history_lines();

    app.apply_session_meta(crate::backend::BackendSessionMeta {
        session_id: app.session_id.clone(),
        command_mode: Some("chat".to_string()),
        session_state: Some("existing".to_string()),
        goal: Some(crate::backend::BackendGoal {
            objective: "finish contract".to_string(),
            status: "completed".to_string(),
        }),
        goal_transition: Some(crate::backend::BackendGoalTransition {
            transition_type: "completed".to_string(),
            objective: Some("finish contract".to_string()),
            status: Some("completed".to_string()),
            previous_objective: None,
            previous_status: None,
        }),
    });

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("goal completed"));
}

#[test]
fn repeated_goal_completion_transition_is_deduplicated() {
    let mut app = App::new();
    let meta = crate::backend::BackendSessionMeta {
        session_id: app.session_id.clone(),
        command_mode: Some("chat".to_string()),
        session_state: Some("existing".to_string()),
        goal: Some(crate::backend::BackendGoal {
            objective: "finish contract".to_string(),
            status: "completed".to_string(),
        }),
        goal_transition: Some(crate::backend::BackendGoalTransition {
            transition_type: "completed".to_string(),
            objective: Some("finish contract".to_string()),
            status: Some("completed".to_string()),
            previous_objective: None,
            previous_status: None,
        }),
    };

    app.apply_session_meta(meta.clone());
    let once = app.take_pending_history_lines();
    app.apply_session_meta(meta);
    let twice = app.take_pending_history_lines();

    let rendered_once = once
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered_once.contains("goal completed"));
    assert!(twice.is_empty());
}

#[test]
fn hydration_announces_goal_clear_transition() {
    let mut app = App::new();
    app.current_goal = Some(crate::backend::BackendGoal {
        objective: "finish contract".to_string(),
        status: "active".to_string(),
    });
    let _ = app.take_pending_history_lines();

    app.apply_session_meta(crate::backend::BackendSessionMeta {
        session_id: app.session_id.clone(),
        command_mode: Some("chat".to_string()),
        session_state: Some("existing".to_string()),
        goal: None,
        goal_transition: Some(crate::backend::BackendGoalTransition {
            transition_type: "cleared".to_string(),
            objective: None,
            status: None,
            previous_objective: Some("finish contract".to_string()),
            previous_status: Some("active".to_string()),
        }),
    });

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("goal cleared"));
}

#[test]
fn hydration_announces_goal_replace_transition() {
    let mut app = App::new();
    app.current_goal = Some(crate::backend::BackendGoal {
        objective: "finish contract".to_string(),
        status: "active".to_string(),
    });
    let _ = app.take_pending_history_lines();

    app.apply_session_meta(crate::backend::BackendSessionMeta {
        session_id: app.session_id.clone(),
        command_mode: Some("chat".to_string()),
        session_state: Some("existing".to_string()),
        goal: Some(crate::backend::BackendGoal {
            objective: "ship goal UX".to_string(),
            status: "active".to_string(),
        }),
        goal_transition: Some(crate::backend::BackendGoalTransition {
            transition_type: "replaced".to_string(),
            objective: Some("ship goal UX".to_string()),
            status: Some("active".to_string()),
            previous_objective: Some("finish contract".to_string()),
            previous_status: Some("active".to_string()),
        }),
    });

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("goal updated"));
    assert!(rendered.contains("ship goal UX"));
}
