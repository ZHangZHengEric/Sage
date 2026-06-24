use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::sync::{Arc, Mutex};
use std::thread;

use anyhow::{anyhow, Result};
#[cfg(test)]
use serde_json::Value;

use crate::backend::protocol::{flush_complete_lines, BackendProtocolState};
use crate::backend::protocol_support::truncate;
use crate::backend::runtime::{
    apply_state_env, prepare_state_root, resolve_cli_invoker, resolve_runtime_root, CliInvoker,
};
use crate::backend::types::{BackendEvent, BackendRequest};

pub struct BackendHandle {
    receiver: Receiver<BackendEvent>,
    child: Arc<Mutex<Child>>,
    stdin: Arc<Mutex<ChildStdin>>,
    config: BackendConfig,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct BackendConfig {
    session_id: String,
    user_id: String,
    agent_id: Option<String>,
    agent_config: Option<PathBuf>,
    agent_mode: Option<String>,
    max_loop_count: Option<u32>,
    workspace: Option<PathBuf>,
    sandbox_type: Option<String>,
    sandbox_approval_mode: String,
    skills: Vec<String>,
    model_override: Option<String>,
    goal_objective: Option<String>,
    goal_status: Option<String>,
    clear_goal: bool,
}

#[cfg(test)]
fn summarize_backend_stderr_line(line: &str) -> String {
    let trimmed = line.trim();
    let Ok(payload) = serde_json::from_str::<Value>(trimmed) else {
        return format!("backend · {trimmed}");
    };

    let level = payload
        .get("level")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or("INFO");
    let file = payload
        .get("file")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or("backend");
    let mut message = payload
        .get("msg")
        .and_then(Value::as_str)
        .map(str::trim)
        .unwrap_or(trimmed)
        .to_string();

    if let Some((head, _)) = message.split_once(" Traceback") {
        message = head.trim().to_string();
    }
    if let Some((head, _)) = message.split_once("Traceback (most recent call last):") {
        message = head.trim().to_string();
    }
    if message.len() > 220 {
        message.truncate(217);
        message.push_str("...");
    }

    format!("backend · {level} {file} {message}")
}

impl BackendHandle {
    pub fn spawn(request: &BackendRequest) -> Result<Self> {
        let runtime_root = resolve_runtime_root()?;
        let state_root = prepare_state_root(&runtime_root)?;
        let cli = resolve_cli_invoker(&runtime_root);
        let workspace = request.workspace.clone();

        let mut command = match &cli {
            CliInvoker::Executable(path) => {
                let mut command = Command::new(path);
                command.current_dir(&runtime_root);
                command
            }
            CliInvoker::PythonModule(path) => {
                let mut command = Command::new(path);
                command
                    .current_dir(&runtime_root)
                    .arg("-u")
                    .arg("-m")
                    .arg("app.cli.main")
                    .env("PYTHONUNBUFFERED", "1");
                command
            }
        };
        command
            .arg("chat")
            .arg("--json")
            .arg("--stats")
            .arg("--session-id")
            .arg(&request.session_id)
            .arg("--user-id")
            .arg(&request.user_id)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if let Some(max_loop_count) = request.max_loop_count {
            command
                .arg("--max-loop-count")
                .arg(max_loop_count.to_string());
        }
        if let Some(workspace) = &workspace {
            command.arg("--workspace").arg(workspace);
        }
        if let Some(sandbox_type) = &request.sandbox_type {
            command
                .arg("--sandbox-type")
                .arg(sandbox_type)
                .env("SAGE_SANDBOX_MODE", sandbox_type);
        }
        command
            .arg("--sandbox-approval-mode")
            .arg(&request.sandbox_approval_mode)
            .env("SAGE_APPROVAL_MODE", &request.sandbox_approval_mode);
        if request.agent_config.is_none() {
            if let Some(agent_id) = &request.agent_id {
                command.arg("--agent-id").arg(agent_id);
            }
        }
        if let Some(agent_config) = &request.agent_config {
            command.arg("--agent-config").arg(agent_config);
        }
        if let Some(agent_mode) = &request.agent_mode {
            command.arg("--agent-mode").arg(agent_mode);
        }
        if request.clear_goal {
            command.arg("--clear-goal");
        } else {
            if let Some(goal_objective) = &request.goal_objective {
                command.arg("--goal").arg(goal_objective);
            }
            if let Some(goal_status) = &request.goal_status {
                command.arg("--goal-status").arg(goal_status);
            }
        }
        for skill in &request.skills {
            command.arg("--skill").arg(skill);
        }
        apply_state_env(&mut command, &state_root);
        if let Some(model) = &request.model_override {
            command.env("SAGE_DEFAULT_LLM_MODEL_NAME", model);
        }

        let mut child = command.spawn().map_err(|err| {
            anyhow!(
                "failed to launch Sage CLI backend with {}: {err}",
                cli.display()
            )
        })?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| anyhow!("missing stdout pipe from backend process"))?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| anyhow!("missing stdin pipe from backend process"))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| anyhow!("missing stderr pipe from backend process"))?;

        let child = Arc::new(Mutex::new(child));
        let stdin = Arc::new(Mutex::new(stdin));
        let reader_child = Arc::clone(&child);
        let (sender, receiver) = mpsc::channel();

        let stderr_sender = sender.clone();
        thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines() {
                match line {
                    Ok(line) if !line.trim().is_empty() => {
                        if let Some(event) = backend_stderr_event(&line) {
                            let _ = stderr_sender.send(event);
                        }
                    }
                    Ok(_) => {}
                    Err(err) => {
                        let _ = stderr_sender.send(BackendEvent::Error(format!(
                            "failed to read backend stderr: {err}"
                        )));
                        return;
                    }
                }
            }
        });

        thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            let mut chunk = [0_u8; 4096];
            let mut pending = Vec::<u8>::new();
            let mut protocol_state = BackendProtocolState::default();

            loop {
                match reader.read(&mut chunk) {
                    Ok(0) => break,
                    Ok(read) => {
                        pending.extend_from_slice(&chunk[..read]);
                        if flush_complete_lines(&mut pending, &sender, &mut protocol_state).is_err()
                        {
                            return;
                        }
                    }
                    Err(err) => {
                        let _ = sender.send(BackendEvent::Error(format!(
                            "failed to read backend output: {err}"
                        )));
                        let _ = sender.send(BackendEvent::Finished);
                        return;
                    }
                }
            }

            if !pending.is_empty() {
                let tail = String::from_utf8_lossy(&pending).trim().to_string();
                if !tail.is_empty() {
                    for event in protocol_state.parse_line(&tail) {
                        if sender.send(event).is_err() {
                            return;
                        }
                    }
                }
            }

            match reader_child.lock() {
                Ok(mut child) => {
                    let _ = child.wait();
                }
                Err(_) => {
                    let _ = sender.send(BackendEvent::Error(
                        "backend process lock poisoned".to_string(),
                    ));
                }
            }
            let _ = sender.send(BackendEvent::Exited);
        });

        Ok(Self {
            receiver,
            child,
            stdin,
            config: BackendConfig {
                session_id: request.session_id.clone(),
                user_id: request.user_id.clone(),
                agent_id: request.agent_id.clone(),
                agent_config: request.agent_config.clone(),
                agent_mode: request.agent_mode.clone(),
                max_loop_count: request.max_loop_count,
                workspace,
                sandbox_type: request.sandbox_type.clone(),
                sandbox_approval_mode: request.sandbox_approval_mode.clone(),
                skills: request.skills.clone(),
                model_override: request.model_override.clone(),
                goal_objective: request.goal_objective.clone(),
                goal_status: request.goal_status.clone(),
                clear_goal: request.clear_goal,
            },
        })
    }

    pub fn try_next(&self) -> Option<BackendEvent> {
        match self.receiver.try_recv() {
            Ok(event) => Some(event),
            Err(TryRecvError::Empty) | Err(TryRecvError::Disconnected) => None,
        }
    }

    pub fn stop(&self) {
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
        }
    }

    pub fn send_prompt(&self, prompt: &str) -> Result<()> {
        let mut stdin = self
            .stdin
            .lock()
            .map_err(|_| anyhow!("backend stdin lock poisoned"))?;
        stdin
            .write_all(prompt.as_bytes())
            .map_err(|err| anyhow!("failed to write prompt to backend: {err}"))?;
        stdin
            .write_all(b"\n")
            .map_err(|err| anyhow!("failed to terminate prompt line: {err}"))?;
        stdin
            .flush()
            .map_err(|err| anyhow!("failed to flush backend stdin: {err}"))?;
        Ok(())
    }

    pub fn matches(&self, request: &BackendRequest) -> bool {
        self.config.session_id == request.session_id
            && self.config.user_id == request.user_id
            && self.config.agent_id == request.agent_id
            && self.config.agent_config == request.agent_config
            && self.config.agent_mode == request.agent_mode
            && self.config.max_loop_count == request.max_loop_count
            && self.config.workspace == request.workspace
            && self.config.sandbox_type == request.sandbox_type
            && self.config.sandbox_approval_mode == request.sandbox_approval_mode
            && self.config.skills == request.skills
            && self.config.model_override == request.model_override
            && self.config.goal_objective == request.goal_objective
            && self.config.goal_status == request.goal_status
            && self.config.clear_goal == request.clear_goal
    }
}

#[cfg(test)]
mod stderr_filter_tests {
    use super::summarize_backend_stderr_line;

    #[test]
    fn summarize_backend_stderr_line_compacts_structured_traceback_json() {
        let rendered = summarize_backend_stderr_line(
            r#"{"level":"ERROR","time":"2026-05-05 05:11:58.399","file":"tool/tool_manager.py:1046","msg":"Tool execution failed for turn_status: 'Session' object has no attribute 'pause_goal' Traceback: Traceback (most recent call last): ..."}"#,
        );

        assert!(rendered.contains("backend · ERROR tool/tool_manager.py:1046"));
        assert!(rendered.contains("Tool execution failed for turn_status"));
        assert!(!rendered.contains("most recent call last"));
    }
}

fn backend_stderr_event(line: &str) -> Option<BackendEvent> {
    let line = line.trim();
    if line.is_empty() || is_ignored_backend_stderr(line) {
        return None;
    }

    let summary = truncate(&line.split_whitespace().collect::<Vec<_>>().join(" "), 220);
    Some(BackendEvent::Status(format!("backend log  {summary}")))
}

fn is_ignored_backend_stderr(line: &str) -> bool {
    line.starts_with("Agent prompt加载完成:")
        || line.starts_with("[working] ")
        || line.contains("token_usage 落库失败")
        || line.contains("token_usage.usage_payload")
        || line.contains("[SQL: INSERT INTO token_usage")
        || line.contains("sqlite3.IntegrityError")
        || line.contains(r#""file": "db.py"#)
        || line.contains(r#""file": "chat_service.py"#)
}

#[cfg(test)]
mod tests {
    use super::backend_stderr_event;
    use crate::backend::BackendEvent;

    #[test]
    fn backend_stderr_ignores_startup_prompt_notice() {
        assert!(
            backend_stderr_event("Agent prompt加载完成: 中文21个, 英文21个, 葡萄牙语21个")
                .is_none()
        );
    }

    #[test]
    fn backend_stderr_ignores_nonfatal_token_usage_persistence_noise() {
        assert!(backend_stderr_event(
            r#"{"level":"ERROR","msg":"token_usage 落库失败: 数据库操作失败: token_usage.usage_payload"}"#
        )
        .is_none());
        assert!(backend_stderr_event(
            r#"{"level":"ERROR","file":"db.py:295","msg":"数据库操作失败: (sqlite3.IntegrityError) NOT NULL constraint failed: token_usage.usage_payload"}"#
        )
        .is_none());
        assert!(backend_stderr_event(
            r#"[SQL: INSERT INTO token_usage (id, session_id) VALUES (?, ?)]"#
        )
        .is_none());
    }

    #[test]
    fn backend_stderr_routes_plain_logs_to_status_instead_of_transcript() {
        let event = backend_stderr_event("loaded optional backend cache").expect("event");

        assert!(matches!(
            event,
            BackendEvent::Status(status) if status.contains("loaded optional backend cache")
        ));
    }

    #[test]
    fn backend_stderr_does_not_fail_requests_from_traceback_lines() {
        let event = backend_stderr_event("Traceback (most recent call last):").expect("event");

        assert!(matches!(
            event,
            BackendEvent::Status(status) if status.contains("Traceback")
        ));
    }
}
