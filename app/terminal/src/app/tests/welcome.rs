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
