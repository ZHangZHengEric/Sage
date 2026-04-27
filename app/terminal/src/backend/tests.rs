use std::env;
use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::MutexGuard;
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::json;

use crate::app::MessageKind;
use crate::backend::contract::{expect_array_field, parse_stream_event, CliJsonCommand};
use crate::backend::protocol::parse_backend_line;
use crate::backend_support::{
    apply_state_env, prepare_state_root, resolve_cli_invoker, resolve_python_command,
    resolve_runtime_root_from, CliInvoker,
};

use super::{BackendEvent, BackendHandle, BackendRequest};

static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn lock_env() -> MutexGuard<'static, ()> {
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

    fn unset(key: &'static str) -> Self {
        let previous = env::var(key).ok();
        unsafe {
            env::remove_var(key);
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

#[test]
fn backend_handle_supports_two_round_trips_without_respawn() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("backend-smoke");
    fs::create_dir_all(&temp_dir).expect("temp dir should be created");
    let script_path = write_fake_backend_script(&temp_dir);
    let log_path = temp_dir.join("backend-prompts.log");
    let _python_guard = EnvVarGuard::set("PYTHON", &script_path.display().to_string());
    let _log_guard = EnvVarGuard::set("TEST_BACKEND_LOG", &log_path.display().to_string());

    let request = BackendRequest {
        session_id: "local-0001".to_string(),
        user_id: "terminal-test".to_string(),
        agent_mode: "simple".to_string(),
        max_loop_count: 3,
        workspace: Some(temp_dir.clone()),
        skills: Vec::new(),
        model_override: None,
        task: "unused".to_string(),
    };

    let handle = BackendHandle::spawn(&request).expect("backend should spawn");

    handle
        .send_prompt("first prompt")
        .expect("first prompt should be written");
    let first_round = collect_round_trip(&handle);
    assert_eq!(first_round, vec!["round 1: first prompt".to_string()]);

    handle
        .send_prompt("second prompt")
        .expect("second prompt should be written");
    let second_round = collect_round_trip(&handle);
    assert_eq!(second_round, vec!["round 2: second prompt".to_string()]);

    let prompts = fs::read_to_string(&log_path).expect("backend log should exist");
    assert_eq!(
        prompts.lines().collect::<Vec<_>>(),
        vec!["first prompt", "second prompt"]
    );

    handle.stop();
    let _ = wait_for_exit(&handle);
}

#[test]
fn prepare_state_root_copies_builtin_skills_into_terminal_workspace() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("builtin-skills");
    let builtin_skill = temp_dir.join("app").join("skills").join("demo-skill");
    fs::create_dir_all(builtin_skill.join("references"))
        .expect("builtin skill directory should be created");
    fs::write(
        builtin_skill.join("SKILL.md"),
        "---\nname: demo-skill\ndescription: demo\n---\n",
    )
    .expect("skill manifest should be written");
    fs::write(
        builtin_skill.join("references").join("guide.md"),
        "demo reference",
    )
    .expect("skill reference should be written");
    let state_root = temp_dir.join("terminal-state");
    let _state_root_guard = EnvVarGuard::set(
        "SAGE_TERMINAL_STATE_ROOT",
        &state_root.display().to_string(),
    );

    let state_root = prepare_state_root(&temp_dir).expect("state root should be prepared");
    let copied_skill = state_root.join("skills").join("demo-skill");
    assert!(copied_skill.join("SKILL.md").is_file());
    assert_eq!(
        fs::read_to_string(copied_skill.join("references").join("guide.md"))
            .expect("copied reference should exist"),
        "demo reference"
    );
}

#[test]
fn prepare_state_root_uses_home_for_packaged_runtime_layout() {
    let _env_lock = lock_env();
    let runtime_root = unique_temp_dir("packaged-runtime");
    fs::create_dir_all(runtime_root.join("app").join("skills")).expect("runtime root should exist");
    let home_dir = unique_temp_dir("terminal-home");
    fs::create_dir_all(&home_dir).expect("home dir should exist");
    let _home_guard = EnvVarGuard::set("HOME", &home_dir.display().to_string());

    let state_root = prepare_state_root(&runtime_root).expect("state root should be prepared");

    assert_eq!(state_root, home_dir.join(".sage").join("terminal-state"));
    assert!(state_root.join("logs").is_dir());
}

#[test]
fn apply_state_env_keeps_default_sage_session_dir() {
    let _env_lock = lock_env();
    let temp_dir = unique_temp_dir("state-env");
    let state_root_path = temp_dir.join("terminal-state");
    let _state_root_guard = EnvVarGuard::set(
        "SAGE_TERMINAL_STATE_ROOT",
        &state_root_path.display().to_string(),
    );
    let state_root = prepare_state_root(&temp_dir).expect("state root should be prepared");
    let mut command = Command::new("true");

    apply_state_env(&mut command, &state_root);

    let envs = command
        .get_envs()
        .map(|(key, value)| {
            (
                key.to_string_lossy().to_string(),
                value.map(|value| value.to_string_lossy().to_string()),
            )
        })
        .collect::<Vec<_>>();

    assert!(!envs.iter().any(|(key, _)| key == "SAGE_SESSION_DIR"));
    assert!(envs.iter().any(|(key, value)| {
        key == "SAGE_LOGS_DIR_PATH"
            && value
                .as_deref()
                .is_some_and(|value| value.ends_with("terminal-state/logs"))
    }));
}

#[test]
fn resolve_runtime_root_prefers_explicit_env_override() {
    let _env_lock = lock_env();
    let runtime_root = unique_temp_dir("runtime-root");
    fs::create_dir_all(runtime_root.join("app").join("cli")).expect("runtime cli dir should exist");
    fs::write(
        runtime_root.join("app").join("cli").join("main.py"),
        "# stub",
    )
    .expect("runtime entry should exist");
    let _runtime_guard = EnvVarGuard::set(
        "SAGE_TERMINAL_RUNTIME_ROOT",
        &runtime_root.display().to_string(),
    );

    let resolved = resolve_runtime_root_from(None).expect("runtime root should resolve");
    assert_eq!(resolved, runtime_root);
}

#[test]
fn resolve_python_command_prefers_bundled_runtime_python() {
    let _env_lock = lock_env();
    let runtime_root = unique_temp_dir("bundled-python");
    let python_path = runtime_root.join(".venv").join("bin").join("python3");
    fs::create_dir_all(python_path.parent().expect("parent should exist"))
        .expect("python dir should exist");
    fs::write(&python_path, "").expect("python stub should be written");
    let _sage_python_guard = EnvVarGuard::unset("SAGE_PYTHON");
    let _python_guard = EnvVarGuard::unset("PYTHON");

    let resolved = resolve_python_command(&runtime_root);
    assert_eq!(resolved, python_path);
}

#[test]
fn resolve_cli_invoker_prefers_explicit_env_override() {
    let _env_lock = lock_env();
    let runtime_root = unique_temp_dir("bundled-cli-env");
    let _cli_guard = EnvVarGuard::set("SAGE_TERMINAL_CLI", "sage");
    let _python_guard = EnvVarGuard::set("SAGE_PYTHON", "/tmp/should-not-be-used");

    let resolved = resolve_cli_invoker(&runtime_root);
    assert_eq!(resolved, CliInvoker::Executable(PathBuf::from("sage")));
}

#[test]
fn resolve_cli_invoker_prefers_bundled_sage_over_python_module() {
    let _env_lock = lock_env();
    let runtime_root = unique_temp_dir("bundled-cli");
    let sage_path = runtime_root.join(".venv").join("bin").join("sage");
    fs::create_dir_all(sage_path.parent().expect("parent should exist"))
        .expect("sage dir should exist");
    fs::write(&sage_path, "").expect("sage stub should be written");
    let _cli_guard = EnvVarGuard::unset("SAGE_TERMINAL_CLI");
    let _python_guard = EnvVarGuard::set("SAGE_PYTHON", "/tmp/python-fallback");

    let resolved = resolve_cli_invoker(&runtime_root);
    assert_eq!(resolved, CliInvoker::Executable(sage_path));
}

#[test]
fn parse_stream_event_collects_tool_fields_from_multiple_locations() {
    let event = parse_stream_event(
        r#"{
            "type":"tool_call",
            "tool_calls":[{"function":{"name":"write_file"}}],
            "metadata":{"tool_name":"shell"},
            "tool_name":"exec"
        }"#,
    )
    .expect("stream event should parse");

    let parsed = parse_backend_line(
        r#"{
            "type":"tool_call",
            "tool_calls":[{"function":{"name":"write_file"}}],
            "metadata":{"tool_name":"shell"},
            "tool_name":"exec",
            "content":"running tools"
        }"#,
    );

    assert_eq!(event.event_type, "tool_call");
    let statuses = parsed
        .into_iter()
        .filter_map(|event| match event {
            BackendEvent::Status(status) => Some(status),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(
        statuses,
        vec!["tool  exec", "tool  shell", "tool  write_file"]
    );
}

#[test]
fn contract_array_field_reports_shape_errors() {
    let payload = json!({"list": {"not": "an array"}});
    let err = expect_array_field(&payload, "list", "sessions.list").expect_err("should fail");
    assert!(err.to_string().contains("sessions.list contract error"));
}

#[test]
fn contract_builds_provider_verify_args_without_user_id() {
    let mutation = crate::backend::ProviderMutation {
        name: Some("demo".to_string()),
        base_url: Some("https://example.com".to_string()),
        api_key: None,
        model: Some("demo-chat".to_string()),
        is_default: Some(false),
    };

    let args = CliJsonCommand::ProviderVerify {
        mutation: &mutation,
    }
    .args();
    assert_eq!(
        args,
        vec![
            "provider",
            "verify",
            "--json",
            "--name",
            "demo",
            "--base-url",
            "https://example.com",
            "--model",
            "demo-chat",
            "--unset-default",
        ]
    );
}

fn collect_round_trip(handle: &BackendHandle) -> Vec<String> {
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut assistant_chunks = Vec::new();

    loop {
        if Instant::now() >= deadline {
            panic!("timed out waiting for backend round trip");
        }

        match handle.try_next() {
            Some(BackendEvent::LiveChunk(MessageKind::Assistant, chunk)) => {
                assistant_chunks.push(chunk)
            }
            Some(BackendEvent::LiveChunk(_, _))
            | Some(BackendEvent::Message(_, _))
            | Some(BackendEvent::Status(_))
            | Some(BackendEvent::ToolStarted(_))
            | Some(BackendEvent::ToolFinished(_)) => {}
            Some(BackendEvent::Finished) => return assistant_chunks,
            Some(BackendEvent::Error(message)) => {
                panic!("backend emitted error during smoke test: {message}")
            }
            Some(BackendEvent::Exited) => {
                panic!("backend exited before finishing the current round trip")
            }
            None => thread::sleep(Duration::from_millis(10)),
        }
    }
}

fn wait_for_exit(handle: &BackendHandle) -> bool {
    let deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < deadline {
        match handle.try_next() {
            Some(BackendEvent::Exited) => return true,
            Some(_) => {}
            None => thread::sleep(Duration::from_millis(10)),
        }
    }
    false
}

fn write_fake_backend_script(temp_dir: &Path) -> PathBuf {
    let script_path = temp_dir.join("fake_backend.py");
    fs::write(
        &script_path,
        r#"#!/usr/bin/env python3
import json
import os
import sys

count = 0
log_path = os.environ.get("TEST_BACKEND_LOG")

for raw in sys.stdin:
    prompt = raw.rstrip("\n")
    count += 1
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(prompt + "\n")
    print(json.dumps({
        "type": "assistant",
        "role": "assistant",
        "content": f"round {count}: {prompt}",
    }), flush=True)
    print(json.dumps({"type": "stream_end"}), flush=True)
"#,
    )
    .expect("script should be written");
    #[cfg(unix)]
    {
        let mut permissions = fs::metadata(&script_path)
            .expect("script metadata should exist")
            .permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&script_path, permissions)
            .expect("script permissions should be updated");
    }
    script_path
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time should be monotonic enough for tests")
        .as_nanos();
    env::temp_dir().join(format!("sage-terminal-{label}-{suffix}"))
}
