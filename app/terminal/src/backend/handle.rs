use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::sync::{Arc, Mutex};
use std::thread;

use anyhow::{anyhow, Result};

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
    agent_mode: String,
    max_loop_count: u32,
    workspace: PathBuf,
    skills: Vec<String>,
    model_override: Option<String>,
}

impl BackendHandle {
    pub fn spawn(request: &BackendRequest) -> Result<Self> {
        let runtime_root = resolve_runtime_root()?;
        let state_root = prepare_state_root(&runtime_root)?;
        let cli = resolve_cli_invoker(&runtime_root);
        let workspace = request
            .workspace
            .clone()
            .unwrap_or_else(|| runtime_root.clone());

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
            .arg("--agent-mode")
            .arg(&request.agent_mode)
            .arg("--max-loop-count")
            .arg(request.max_loop_count.to_string())
            .arg("--workspace")
            .arg(&workspace)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
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
