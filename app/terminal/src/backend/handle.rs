use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::sync::{Arc, Mutex};
use std::thread;

use anyhow::{anyhow, Result};
use serde_json::Value;

use crate::app::MessageKind;
use crate::backend::protocol::{flush_complete_lines, parse_backend_line};
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
    agent_mode: String,
    max_loop_count: u32,
    workspace: Option<PathBuf>,
    skills: Vec<String>,
    model_override: Option<String>,
    goal_objective: Option<String>,
    goal_status: Option<String>,
    clear_goal: bool,
}

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
            .arg("--max-loop-count")
            .arg(request.max_loop_count.to_string())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if let Some(workspace) = &workspace {
            command.arg("--workspace").arg(workspace);
        }
        if let Some(agent_id) = &request.agent_id {
            command.arg("--agent-id").arg(agent_id);
        }
        command.arg("--agent-mode").arg(&request.agent_mode);
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
                        let _ = stderr_sender.send(BackendEvent::Message(
                            MessageKind::System,
                            summarize_backend_stderr_line(&line),
                        ));
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

            loop {
                match reader.read(&mut chunk) {
                    Ok(0) => break,
                    Ok(read) => {
                        pending.extend_from_slice(&chunk[..read]);
                        if flush_complete_lines(&mut pending, &sender).is_err() {
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
                    for event in parse_backend_line(&tail) {
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
                agent_mode: request.agent_mode.clone(),
                max_loop_count: request.max_loop_count,
                workspace,
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
            && self.config.agent_mode == request.agent_mode
            && self.config.max_loop_count == request.max_loop_count
            && self.config.workspace == request.workspace
            && self.config.skills == request.skills
            && self.config.model_override == request.model_override
            && self.config.goal_objective == request.goal_objective
            && self.config.goal_status == request.goal_status
            && self.config.clear_goal == request.clear_goal
    }
}

#[cfg(test)]
mod tests {
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
