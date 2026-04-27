mod contract;
mod handle;
mod runtime;

use std::env;
use std::fs;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::MutexGuard;
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::app::MessageKind;
use crate::backend::{BackendEvent, BackendHandle};

static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

pub(super) fn lock_env() -> MutexGuard<'static, ()> {
    ENV_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

pub(super) struct EnvVarGuard {
    key: &'static str,
    previous: Option<String>,
}

impl EnvVarGuard {
    pub(super) fn set(key: &'static str, value: &str) -> Self {
        let previous = env::var(key).ok();
        unsafe {
            env::set_var(key, value);
        }
        Self { key, previous }
    }

    pub(super) fn unset(key: &'static str) -> Self {
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

pub(super) fn collect_round_trip(handle: &BackendHandle) -> Vec<String> {
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

pub(super) fn wait_for_exit(handle: &BackendHandle) -> bool {
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

pub(super) fn write_fake_backend_script(temp_dir: &Path) -> PathBuf {
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

pub(super) fn unique_temp_dir(label: &str) -> PathBuf {
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time should be monotonic enough for tests")
        .as_nanos();
    env::temp_dir().join(format!("sage-terminal-{label}-{suffix}"))
}
