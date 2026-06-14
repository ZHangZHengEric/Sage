use super::super::App;
use unicode_width::UnicodeWidthStr;

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
    assert!(rendered.contains("agent mode: "));
    assert!(rendered.contains("display: "));
    assert!(rendered.contains("compact"));
    assert!(rendered.contains("workspace: "));
    assert!(rendered.contains("goal: "));
    assert!(rendered.contains("session: "));
    assert!(rendered.contains("new"));
    assert!(rendered.contains("Tip: "));
}

#[test]
fn welcome_banner_uses_available_terminal_width() {
    let app = App::new();
    let lines = app.rendered_idle_lines(120);
    let first_line = lines
        .first()
        .map(|line| {
            line.spans
                .iter()
                .map(|span| span.content.as_ref())
                .collect::<Vec<_>>()
                .join("")
        })
        .unwrap_or_default();

    assert!(UnicodeWidthStr::width(first_line.as_str()) >= 110);
}

#[test]
fn welcome_banner_labels_agent_config_owned_values() {
    let mut app = App::new();
    app.set_agent_config_path("coding".to_string());

    let rendered = app
        .rendered_idle_lines(120)
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");

    assert!(rendered.contains("agent: "));
    assert!(rendered.contains("config coding"));
    assert!(rendered.contains("config default"));
    assert!(!rendered.contains("agent: \n(default)"));
    assert!(!rendered.contains("loop limit: \n50"));
}

#[test]
fn first_task_materializes_local_session_id() {
    let mut app = App::new();
    assert_eq!(app.session_label(), "new");

    app.input = "inspect this repo".to_string();
    app.input_cursor = app.input.len();
    let _ = app.submit_input();

    assert_ne!(app.session_label(), "new");
    assert!(app.session_id.starts_with("local-"));
}

#[test]
fn welcome_banner_renders_current_goal_when_present() {
    let mut app = App::new();
    app.set_goal_selection("ship the runtime goal contract".to_string());
    app.pending_goal_mutation = None;

    let lines = app.rendered_idle_lines(120);
    let rendered = lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");

    assert!(rendered.contains("goal: "));
    assert!(rendered.contains("ship the runtime goal contract"));
    assert!(rendered.contains("(active)"));
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
fn submitting_message_keeps_welcome_banner_as_idle_status() {
    let mut app = App::new();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let _ = app.submit_input();
    app.materialize_pending_ui(120);

    let rendered = app
        .rendered_idle_lines(120)
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("Sage Terminal"));
    assert!(rendered.contains("workspace: "));
}

#[test]
fn first_message_requests_clear_before_transcript_history_is_inserted() {
    let mut app = App::new();
    let _ = app.take_clear_request();
    app.input = "hello".to_string();
    app.input_cursor = app.input.len();

    let _ = app.submit_input();
    app.materialize_pending_ui(120);

    assert!(app.take_clear_request());
    assert!(!app.take_clear_request());
}

#[test]
fn first_transcript_keeps_welcome_out_of_history_but_visible_when_idle() {
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
    assert!(!rendered.contains("Sage Terminal"));
    assert!(!rendered.contains("Tip: "));
    assert!(rendered.contains("hello"));
    assert!(!app.rendered_idle_lines(120).is_empty());
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
fn help_agent_topic_mentions_config_commands() {
    let mut app = App::new();
    app.input = "/help agent".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();
    assert!(matches!(action, super::super::SubmitAction::Handled));
    let props = app.help_overlay_props().expect("help overlay should open");
    assert_eq!(props.title, "Help  /agent");
    let text = props
        .sections
        .iter()
        .flat_map(|section| section.items.iter())
        .map(|item| item.value.as_str())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(text.contains("/agent config <path|coding>"));
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
