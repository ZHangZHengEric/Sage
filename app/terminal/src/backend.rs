use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::sync::{Arc, Mutex};
use std::thread;

use anyhow::{anyhow, Result};

use crate::app::MessageKind;
use crate::backend_support::{
    apply_state_env, prepare_state_root, repo_root,
};

#[path = "backend/api.rs"]
mod api;
#[path = "backend/protocol.rs"]
mod protocol;
#[cfg(test)]
#[path = "backend/tests.rs"]
mod tests;

pub(crate) use api::{
    create_provider, delete_provider, inspect_latest_session, inspect_provider, inspect_session,
    list_providers, list_sessions, list_skills, read_config, set_default_provider, update_provider,
};
use protocol::{flush_complete_lines, parse_backend_line};

pub struct SessionSummary {
    pub session_id: String,
    pub title: String,
    pub message_count: u64,
    pub updated_at: String,
    pub last_preview: Option<String>,
}

pub struct SessionDetail {
    pub session_id: String,
    pub title: String,
    pub message_count: u64,
    pub updated_at: String,
    pub recent_messages: Vec<SessionMessage>,
}

pub struct SessionMessage {
    pub role: String,
    pub content: String,
}

pub struct SkillInfo {
    pub name: String,
    pub description: String,
    pub source: String,
}

pub struct ConfigInfo {
    pub default_model_name: String,
    pub default_api_base_url: String,
    pub default_user_id: String,
    pub env_file: String,
}

pub struct ProviderInfo {
    pub id: String,
    pub name: String,
    pub model: String,
    pub base_url: String,
    pub is_default: bool,
    pub api_key_preview: String,
}

#[derive(Debug)]
pub struct ProviderMutation {
    pub name: Option<String>,
    pub base_url: Option<String>,
    pub api_key: Option<String>,
    pub model: Option<String>,
    pub is_default: Option<bool>,
}

pub struct BackendRequest {
    pub session_id: String,
    pub user_id: String,
    pub agent_mode: String,
    pub max_loop_count: u32,
    pub workspace: Option<PathBuf>,
    pub skills: Vec<String>,
    pub model_override: Option<String>,
    pub task: String,
}

pub enum BackendEvent {
    LiveChunk(MessageKind, String),
    Message(MessageKind, String),
    Status(String),
    ToolStarted(String),
    ToolFinished(String),
    Error(String),
    Finished,
    Exited,
}

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
    agent_mode: String,
    max_loop_count: u32,
    workspace: PathBuf,
    skills: Vec<String>,
    model_override: Option<String>,
}

impl BackendHandle {
    pub fn spawn(request: &BackendRequest) -> Result<Self> {
        let repo_root = repo_root()?;
        let state_root = prepare_state_root(&repo_root)?;
        let python = std::env::var("PYTHON").unwrap_or_else(|_| "python3".to_string());
        let workspace = request
            .workspace
            .clone()
            .unwrap_or_else(|| repo_root.clone());

        let mut command = Command::new(&python);
        command
            .current_dir(&repo_root)
            .arg("-u")
            .arg("-m")
            .arg("app.cli.main")
            .arg("chat")
            .arg("--json")
            .arg("--stats")
            .arg("--session-id")
            .arg(&request.session_id)
            .arg("--user-id")
            .arg(&request.user_id)
            .arg("--agent-mode")
            .arg(&request.agent_mode)
            .arg("--max-loop-count")
            .arg(request.max_loop_count.to_string())
            .arg("--workspace")
            .arg(&workspace)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env("PYTHONUNBUFFERED", "1");
        for skill in &request.skills {
            command.arg("--skill").arg(skill);
        }
        apply_state_env(&mut command, &state_root);
        if let Some(model) = &request.model_override {
            command.env("SAGE_DEFAULT_LLM_MODEL_NAME", model);
        }

        let mut child = command
            .spawn()
            .map_err(|err| anyhow!("failed to launch Sage CLI backend with {python}: {err}"))?;
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
                            format!("backend · {}", line.trim()),
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
                agent_mode: request.agent_mode.clone(),
                max_loop_count: request.max_loop_count,
                workspace,
                skills: request.skills.clone(),
                model_override: request.model_override.clone(),
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
            && self.config.agent_mode == request.agent_mode
            && self.config.max_loop_count == request.max_loop_count
            && self.config.workspace
                == request
                    .workspace
                    .clone()
                    .unwrap_or_else(|| self.config.workspace.clone())
            && self.config.skills == request.skills
            && self.config.model_override == request.model_override
    }
}
