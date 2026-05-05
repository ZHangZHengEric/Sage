use crossterm::event::{KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::app::{ActiveSurfaceKind, App, MessageKind, SubmitAction};
use crate::slash_command;

use super::super::{handle_key, INLINE_VIEWPORT_IDLE_HEIGHT, INLINE_VIEWPORT_MAX_HEIGHT};
use crate::terminal_layout::desired_viewport_height;

#[test]
fn terminal_loop_accepts_repeat_key_events_for_submission() {
    assert!(super::super::should_handle_key_event(KeyEventKind::Press));
    assert!(super::super::should_handle_key_event(KeyEventKind::Repeat));
    assert!(!super::super::should_handle_key_event(KeyEventKind::Release));
}

#[test]
fn key_debug_toggle_defaults_to_disabled() {
    std::env::remove_var("SAGE_TERMINAL_DEBUG_KEYS");
    super::super::emit_key_debug_if_enabled(&KeyEvent::new(
        KeyCode::Enter,
        KeyModifiers::NONE,
    ));
}

#[test]
fn help_overlay_consumes_typing_without_mutating_input() {
    let mut app = App::new();
    app.input = "/help".to_string();
    app.input_cursor = app.input.len();
    assert!(matches!(app.submit_input(), SubmitAction::Handled));

    let mut backend = None;
    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Char('x'), KeyModifiers::NONE),
        &mut backend,
    )
    .expect("typing while help is open should not fail");

    assert!(handled);
    assert!(app.help_overlay_props().is_some());
    assert!(app.input.is_empty());
}

#[test]
fn help_overlay_enter_closes_modal() {
    let mut app = App::new();
    app.input = "/help".to_string();
    app.input_cursor = app.input.len();
    assert!(matches!(app.submit_input(), SubmitAction::Handled));

    let mut backend = None;
    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("enter while help is open should not fail");

    assert!(handled);
    assert!(app.help_overlay_props().is_none());
}

#[test]
fn welcome_banner_expands_idle_viewport_height() {
    let app = App::new();

    assert!(
        desired_viewport_height(
            &app,
            120,
            INLINE_VIEWPORT_IDLE_HEIGHT,
            INLINE_VIEWPORT_MAX_HEIGHT
        ) > INLINE_VIEWPORT_IDLE_HEIGHT
    );
}

#[test]
fn esc_quits_when_idle_and_input_is_empty() {
    let mut app = App::new();
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("esc should not fail");

    assert!(handled);
    assert!(app.should_quit);
}

#[test]
fn esc_clears_input_before_quitting() {
    let mut app = App::new();
    app.input = "draft".to_string();
    app.input_cursor = app.input.len();
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("esc should not fail");

    assert!(handled);
    assert!(app.input.is_empty());
    assert!(!app.should_quit);
}

#[test]
fn esc_closes_popup_before_quitting() {
    let mut app = App::new();
    app.input = "/pro".to_string();
    app.input_cursor = app.input.len();
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("esc should not fail");

    assert!(handled);
    assert!(app.input.is_empty());
    assert!(!app.should_quit);
}

#[test]
fn help_popup_submit_escape_and_welcome_flow_stays_consistent() {
    let mut app = App::new();
    let mut backend = None;

    app.input = "/he".to_string();
    app.input_cursor = app.input.len();
    assert_eq!(app.active_surface_kind(), Some(ActiveSurfaceKind::Popup));

    assert!(app.autocomplete_popup());
    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("popup submit should not fail");
    assert!(handled);
    assert!(app.help_overlay_props().is_some());

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("help escape should not fail");
    assert!(handled);
    assert!(app.help_overlay_props().is_none());

    app.input = "hello".to_string();
    app.input_cursor = app.input.len();
    let action = app.submit_input();
    assert!(matches!(action, SubmitAction::RunTask(_)));
    app.materialize_pending_ui(120);
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("Sage Terminal"));
    assert!(rendered.contains("hello"));
}

#[test]
fn ctrl_t_opens_transcript_overlay_when_idle() {
    let mut app = App::new();
    app.push_message(MessageKind::User, "hello");
    let _ = app.take_pending_history_lines();
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Char('t'), KeyModifiers::CONTROL),
        &mut backend,
    )
    .expect("ctrl-t should not fail");

    assert!(handled);
    assert_eq!(
        app.active_surface_kind(),
        Some(ActiveSurfaceKind::Transcript)
    );
}

#[test]
fn shift_enter_inserts_newline_without_submitting() {
    let mut app = App::new();
    app.input = "first line".to_string();
    app.input_cursor = app.input.len();
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Enter, KeyModifiers::SHIFT),
        &mut backend,
    )
    .expect("shift-enter should not fail");

    assert!(handled);
    assert_eq!(app.input, "first line\n");
    assert!(!app.busy);
}

#[test]
fn popup_visible_enter_submits_typed_slash_command_instead_of_selected_popup_item() {
    let mut app = App::new();
    app.input = "/exit".to_string();
    app.input_cursor = app.input.len();
    let mut backend = None;

    assert!(app.popup_props().is_some());
    assert!(slash_command::find("/exit").is_some());

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("enter should submit typed slash command");

    assert!(handled);
    assert!(app.should_quit);
}

#[test]
fn display_command_switches_mode_through_normal_input_flow() {
    let mut app = App::new();
    app.input = "/display set verbose".to_string();
    app.input_cursor = app.input.len();

    let action = app.submit_input();
    assert!(matches!(action, SubmitAction::Handled));
    assert_eq!(
        app.display_mode,
        crate::display_policy::DisplayMode::Verbose
    );
}

#[test]
fn ctrl_c_interrupts_busy_request_instead_of_quitting() {
    let mut app = App::new();
    app.begin_task_submission("keep running".to_string(), true);
    app.append_assistant_chunk("partial");
    let mut backend = None;

    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Char('c'), KeyModifiers::CONTROL),
        &mut backend,
    )
    .expect("ctrl-c while busy should not fail");

    assert!(handled);
    assert!(!app.should_quit);
    assert!(!app.busy);
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("interrupted"));
    assert!(rendered.contains("/retry available"));
}

#[test]
fn interrupt_command_stops_busy_request_through_normal_input_flow() {
    let mut app = App::new();
    app.begin_task_submission("keep running".to_string(), true);
    app.append_assistant_chunk("partial");
    app.input = "/interrupt".to_string();
    app.input_cursor = app.input.len();

    let mut backend = None;
    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("interrupt submit should not fail");

    assert!(handled);
    assert!(!app.busy);
    assert!(!app.should_quit);
    let rendered = app
        .pending_history_lines
        .iter()
        .flat_map(|line| line.spans.iter())
        .map(|span| span.content.as_ref())
        .collect::<Vec<_>>()
        .join("\n");
    assert!(rendered.contains("interrupted"));
    assert!(rendered.contains("partial output preserved • /retry available"));
}

#[test]
fn busy_state_allows_typing_slash_interrupt_command() {
    let mut app = App::new();
    app.begin_task_submission("keep running".to_string(), true);
    let mut backend = None;

    for ch in "/interrupt".chars() {
        let handled = handle_key(
            &mut app,
            KeyEvent::new(KeyCode::Char(ch), KeyModifiers::NONE),
            &mut backend,
        )
        .expect("typing slash command while busy should not fail");
        assert!(handled);
    }

    assert_eq!(app.input, "/interrupt");
}

#[test]
fn retry_command_resubmits_last_task_through_backend() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("terminal-retry");
    fs::create_dir_all(&temp_dir).expect("temp dir should exist");
    let script_path = write_fake_backend_script(&temp_dir);
    let log_path = temp_dir.join("backend-prompts.log");
    let _python_guard = EnvVarGuard::set("PYTHON", &script_path.display().to_string());
    let _log_guard = EnvVarGuard::set("TEST_BACKEND_LOG", &log_path.display().to_string());

    let mut app = App::new();
    app.begin_task_submission("retry me".to_string(), true);
    app.interrupt_request();
    app.clear_input();
    app.input = "/retry".to_string();
    app.input_cursor = app.input.len();

    let mut backend = None;
    let handled = handle_key(
        &mut app,
        KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE),
        &mut backend,
    )
    .expect("retry submit should not fail");

    assert!(handled);
    assert!(app.busy);
    assert_eq!(app.current_task.as_deref(), Some("retry me"));

    wait_for_prompt_log(&log_path, "retry me");
    let prompts = fs::read_to_string(&log_path).expect("backend log should exist");
    assert_eq!(prompts.lines().collect::<Vec<_>>(), vec!["retry me"]);
}

fn lock_env() -> MutexGuard<'static, ()> {
    static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    ENV_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

struct EnvVarGuard {
    key: &'static str,
    previous: Option<String>,
}

impl EnvVarGuard {
    fn set(key: &'static str, value: &str) -> Self {
        let previous = env::var(key).ok();
        unsafe {
            env::set_var(key, value);
        }
        Self { key, previous }
    }
}

impl Drop for EnvVarGuard {
    fn drop(&mut self) {
        match &self.previous {
            Some(value) => unsafe {
                env::set_var(self.key, value);
            },
            None => unsafe {
                env::remove_var(self.key);
            },
        }
    }
}

fn write_fake_backend_script(temp_dir: &Path) -> PathBuf {
    let script_path = temp_dir.join("fake_backend.py");
    fs::write(
        &script_path,
        r#"#!/usr/bin/env python3
import json
import os
import sys

log_path = os.environ.get("TEST_BACKEND_LOG")

for raw in sys.stdin:
    prompt = raw.rstrip("\n")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(prompt + "\n")
    print(json.dumps({
        "type": "assistant",
        "role": "assistant",
        "content": f"echo: {prompt}",
    }), flush=True)
    print(json.dumps({"type": "stream_end"}), flush=True)
    print(json.dumps({
        "type": "cli_stats",
        "elapsed_seconds": 0.001,
        "first_output_seconds": 0.001,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
    }), flush=True)
"#,
    )
    .expect("script should be written");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        let mut permissions = fs::metadata(&script_path)
            .expect("script metadata should exist")
            .permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&script_path, permissions)
            .expect("script permissions should be updated");
    }
    script_path
}

fn wait_for_prompt_log(log_path: &Path, expected_prompt: &str) {
    let deadline = Instant::now() + Duration::from_secs(3);
    while Instant::now() < deadline {
        if let Ok(contents) = fs::read_to_string(log_path) {
            if contents.lines().any(|line| line == expected_prompt) {
                return;
            }
        }
        thread::sleep(Duration::from_millis(10));
    }
    panic!("timed out waiting for prompt log entry: {expected_prompt}");
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time should move forward")
        .as_nanos();
    env::temp_dir().join(format!("sage-terminal-{label}-{suffix}"))
}
