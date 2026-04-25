use std::env;
use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::app::MessageKind;
use crate::backend_support::{apply_state_env, prepare_state_root};

use super::{BackendEvent, BackendHandle, BackendRequest};

static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

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

#[test]
fn backend_handle_supports_two_round_trips_without_respawn() {
    let _env_lock = ENV_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .expect("env lock poisoned");
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
fn apply_state_env_keeps_default_sage_session_dir() {
    let temp_dir = unique_temp_dir("state-env");
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
                .is_some_and(|value| value.contains(".sage-terminal-state"))
    }));
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
