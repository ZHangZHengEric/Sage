use super::super::App;

#[test]
fn welcome_banner_renders_in_idle_region_before_transcript() {
    let app = App::new();
    let lines = app.rendered_idle_lines(120);

    assert!(!lines.is_empty());
    let rendered = lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("Sage Terminal"));
    assert!(rendered.contains("display: "));
    assert!(rendered.contains("compact"));
    assert!(rendered.contains("Tip: "));
}

#[test]
fn typing_input_keeps_welcome_banner_visible() {
    let mut app = App::new();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let lines = app.rendered_idle_lines(120);

    assert!(!lines.is_empty());
}

#[test]
fn submitting_message_hides_welcome_banner() {
    let mut app = App::new();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let _ = app.submit_input();
    app.materialize_pending_ui(120);

    assert!(app.rendered_idle_lines(120).is_empty());
}

#[test]
fn first_transcript_materializes_welcome_into_history() {
    let mut app = App::new();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let _ = app.submit_input();
    app.materialize_pending_ui(120);

    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("Sage Terminal"));
    assert!(rendered.contains("Tip: "));
    assert!(rendered.contains("hello"));
    assert!(app.rendered_idle_lines(120).is_empty());
}

#[test]
fn help_command_opens_overlay_without_queueing_history() {
    let mut app = App::new();
    app.input = "/help".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();
    assert!(matches!(action, super::super::SubmitAction::Handled));
    assert!(app.help_overlay_props().is_some());
    assert!(app.pending_history_lines.is_empty());
}

#[test]
fn help_command_topic_opens_detail_overlay() {
    let mut app = App::new();
    app.input = "/help provider".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();
    assert!(matches!(action, super::super::SubmitAction::Handled));
    let props = app.help_overlay_props().expect("help overlay should open");
    assert_eq!(props.title, "Help  /provider");
    assert!(props
        .sections
        .iter()
        .flat_map(|section| section.items.iter())
        .any(|item| item.value.contains("/provider create")));
}

#[test]
fn doctor_command_returns_doctor_action() {
    let mut app = App::new();
    app.input = "/doctor probe-provider".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();
    assert!(matches!(
        action,
        super::super::SubmitAction::ShowDoctor {
            probe_provider: true
        }
    ));
}

#[test]
fn config_init_command_returns_init_action() {
    let mut app = App::new();
    app.input = "/config init /tmp/demo.env --force".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();
    assert!(matches!(
        action,
        super::super::SubmitAction::InitConfig {
            path: Some(path),
            force: true
        } if path == "/tmp/demo.env"
    ));
}

#[test]
fn provider_verify_command_returns_verify_action() {
    let mut app = App::new();
    app.input = "/provider verify model=demo-chat".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();
    assert!(matches!(
        action,
        super::super::SubmitAction::VerifyProvider(fields)
            if fields == vec!["model=demo-chat".to_string()]
    ));
}

#[test]
fn sessions_inspect_command_returns_show_session_action() {
    let mut app = App::new();
    app.input = "/sessions inspect latest".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();
    assert!(matches!(
        action,
        super::super::SubmitAction::ShowSession(session_id)
            if session_id == "latest"
    ));
}
