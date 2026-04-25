use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::sync::{Arc, Mutex};
use std::thread;

use anyhow::{anyhow, Result};
use serde_json::Value;

use crate::app::MessageKind;
use crate::backend_support::{
    apply_state_env, prepare_state_root, repo_root, run_cli_json, run_cli_json_owned,
};

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

pub fn list_sessions(user_id: &str, limit: usize) -> Result<Vec<SessionSummary>> {
    let limit = limit.max(1).to_string();
    let value = run_cli_json(&[
        "sessions",
        "--json",
        "--user-id",
        user_id,
        "--limit",
        &limit,
    ])?;

    let items = value
        .get("list")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();

    Ok(items.iter().map(parse_session_summary).collect::<Vec<_>>())
}

pub fn inspect_latest_session(user_id: &str) -> Result<Option<SessionDetail>> {
    inspect_session_impl("latest", user_id)
}

pub fn inspect_session(session_id: &str, user_id: &str) -> Result<Option<SessionDetail>> {
    inspect_session_impl(session_id, user_id)
}

pub fn list_skills(user_id: &str, workspace: Option<&std::path::Path>) -> Result<Vec<SkillInfo>> {
    let mut args = vec!["skills", "--json", "--user-id", user_id];
    let workspace_owned;
    if let Some(path) = workspace {
        workspace_owned = path.display().to_string();
        args.push("--workspace");
        args.push(&workspace_owned);
    }

    let value = run_cli_json(&args)?;
    let items = value
        .get("list")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();

    Ok(items
        .into_iter()
        .map(|item| SkillInfo {
            name: item
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            description: item
                .get("description")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            source: item
                .get("source")
                .and_then(Value::as_str)
                .unwrap_or("unknown")
                .to_string(),
        })
        .collect())
}

pub fn read_config() -> Result<ConfigInfo> {
    let value = run_cli_json(&["config", "show", "--json"])?;
    Ok(ConfigInfo {
        default_model_name: value
            .get("default_llm_model_name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        default_api_base_url: value
            .get("default_llm_api_base_url")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        default_user_id: value
            .get("default_cli_user_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        env_file: value
            .get("env_file")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
    })
}

pub fn list_providers(user_id: &str) -> Result<Vec<ProviderInfo>> {
    let value = run_cli_json(&["provider", "list", "--json", "--user-id", user_id])?;
    let items = value
        .get("list")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();

    Ok(items
        .into_iter()
        .map(|item| ProviderInfo {
            id: item
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            name: item
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            model: item
                .get("model")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            base_url: item
                .get("base_url")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
            is_default: item
                .get("is_default")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            api_key_preview: item
                .get("api_key_preview")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string(),
        })
        .collect())
}

pub fn inspect_provider(user_id: &str, provider_id: &str) -> Result<ProviderInfo> {
    let value = run_cli_json(&[
        "provider",
        "inspect",
        provider_id,
        "--json",
        "--user-id",
        user_id,
    ])?;
    let provider = value
        .get("provider")
        .ok_or_else(|| anyhow!("provider payload missing"))?;
    Ok(parse_provider(provider))
}

pub fn set_default_provider(user_id: &str, provider_id: &str) -> Result<ProviderInfo> {
    let value = run_cli_json(&[
        "provider",
        "update",
        provider_id,
        "--json",
        "--user-id",
        user_id,
        "--set-default",
    ])?;
    let provider = value
        .get("provider")
        .ok_or_else(|| anyhow!("provider payload missing"))?;
    Ok(parse_provider(provider))
}

pub fn create_provider(user_id: &str, mutation: &ProviderMutation) -> Result<ProviderInfo> {
    let args = build_provider_mutation_args("create", Some(user_id), None, mutation);
    let value = run_cli_json_owned(&args)?;
    let provider = value
        .get("provider")
        .ok_or_else(|| anyhow!("provider payload missing"))?;
    Ok(parse_provider(provider))
}

pub fn update_provider(
    user_id: &str,
    provider_id: &str,
    mutation: &ProviderMutation,
) -> Result<ProviderInfo> {
    let args = build_provider_mutation_args("update", Some(user_id), Some(provider_id), mutation);
    let value = run_cli_json_owned(&args)?;
    let provider = value
        .get("provider")
        .ok_or_else(|| anyhow!("provider payload missing"))?;
    Ok(parse_provider(provider))
}

pub fn delete_provider(user_id: &str, provider_id: &str) -> Result<()> {
    let value = run_cli_json(&[
        "provider",
        "delete",
        provider_id,
        "--json",
        "--user-id",
        user_id,
    ])?;
    let deleted = value
        .get("deleted")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if deleted {
        Ok(())
    } else {
        Err(anyhow!("provider delete did not report success"))
    }
}

fn flush_complete_lines(
    pending: &mut Vec<u8>,
    sender: &mpsc::Sender<BackendEvent>,
) -> Result<(), mpsc::SendError<BackendEvent>> {
    while let Some(index) = pending.iter().position(|byte| *byte == b'\n') {
        let line = pending.drain(..=index).collect::<Vec<_>>();
        let line = String::from_utf8_lossy(&line);
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        for event in parse_backend_line(line) {
            sender.send(event)?;
        }
    }
    Ok(())
}

fn parse_backend_line(line: &str) -> Vec<BackendEvent> {
    let mut events = Vec::new();
    let value = match serde_json::from_str::<Value>(line) {
        Ok(value) => value,
        Err(_) => return events,
    };

    let event_type = value
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let role = value
        .get("role")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let content = value
        .get("content")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let tool_names = collect_tool_names(&value);

    if event_type == "cli_stats" {
        events.push(BackendEvent::Finished);
    } else if let Some(kind) = live_message_kind(event_type, role, &content) {
        events.push(BackendEvent::LiveChunk(kind, content));
    } else if matches!(event_type, "tool_call" | "tool_result") && !tool_names.is_empty() {
        for name in &tool_names {
            events.push(if event_type == "tool_call" {
                BackendEvent::ToolStarted(name.clone())
            } else {
                BackendEvent::ToolFinished(name.clone())
            });
        }
    } else if !content.is_empty() {
        match event_type {
            "tool_call" => events.push(BackendEvent::Message(
                MessageKind::Tool,
                format!("running {}", summarize_tool_event(&tool_names, &content)),
            )),
            "tool_result" => events.push(BackendEvent::Message(
                MessageKind::Tool,
                format!("completed {}", summarize_tool_event(&tool_names, &content)),
            )),
            "error" | "cli_error" => events.push(BackendEvent::Error(content)),
            "cli_stats" | "token_usage" | "start" | "done" => {}
            _ => events.push(BackendEvent::Message(
                MessageKind::Process,
                truncate(&clean_single_line(&content), 180),
            )),
        }
    }

    for name in tool_names {
        events.push(BackendEvent::Status(format!("tool  {}", name)));
    }

    if event_type == "stream_end" {
        events.push(BackendEvent::Finished);
    }

    events
}

fn inspect_session_impl(session_id: &str, user_id: &str) -> Result<Option<SessionDetail>> {
    let value = run_cli_json(&[
        "sessions",
        "inspect",
        session_id,
        "--json",
        "--user-id",
        user_id,
    ])?;

    if value.is_null() {
        return Ok(None);
    }

    Ok(Some(parse_session_detail(&value)))
}

fn parse_session_summary(value: &Value) -> SessionSummary {
    SessionSummary {
        session_id: value
            .get("session_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        title: value
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or("(untitled)")
            .to_string(),
        message_count: value
            .get("message_count")
            .and_then(Value::as_u64)
            .unwrap_or(0),
        updated_at: value
            .get("updated_at")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        last_preview: value
            .get("last_message")
            .and_then(Value::as_object)
            .and_then(|last| last.get("content"))
            .and_then(Value::as_str)
            .map(compact_preview),
    }
}

fn parse_session_detail(value: &Value) -> SessionDetail {
    let recent_messages = value
        .get("recent_messages")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter_map(|item| {
            let role = item.get("role").and_then(Value::as_str)?.to_string();
            let content = item.get("content").and_then(Value::as_str)?.to_string();
            Some(SessionMessage { role, content })
        })
        .collect::<Vec<_>>();

    SessionDetail {
        session_id: value
            .get("session_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        title: value
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or("(untitled)")
            .to_string(),
        message_count: value
            .get("message_count")
            .and_then(Value::as_u64)
            .unwrap_or(0),
        updated_at: value
            .get("updated_at")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        recent_messages,
    }
}

fn compact_preview(text: &str) -> String {
    text.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(120)
        .collect::<String>()
}

fn parse_provider(value: &Value) -> ProviderInfo {
    ProviderInfo {
        id: value
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        name: value
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        model: value
            .get("model")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        base_url: value
            .get("base_url")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        is_default: value
            .get("is_default")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        api_key_preview: value
            .get("api_key_preview")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
    }
}

fn build_provider_mutation_args(
    command: &str,
    user_id: Option<&str>,
    provider_id: Option<&str>,
    mutation: &ProviderMutation,
) -> Vec<String> {
    let mut args = vec!["provider".to_string(), command.to_string()];
    if let Some(provider_id) = provider_id {
        args.push(provider_id.to_string());
    }
    if let Some(user_id) = user_id {
        args.push("--user-id".to_string());
        args.push(user_id.to_string());
    }
    args.push("--json".to_string());

    if let Some(name) = &mutation.name {
        args.push("--name".to_string());
        args.push(name.clone());
    }
    if let Some(base_url) = &mutation.base_url {
        args.push("--base-url".to_string());
        args.push(base_url.clone());
    }
    if let Some(api_key) = &mutation.api_key {
        args.push("--api-key".to_string());
        args.push(api_key.clone());
    }
    if let Some(model) = &mutation.model {
        args.push("--model".to_string());
        args.push(model.clone());
    }
    if let Some(is_default) = mutation.is_default {
        args.push(if is_default {
            "--set-default".to_string()
        } else {
            "--unset-default".to_string()
        });
    }

    args
}

fn live_message_kind(event_type: &str, role: &str, content: &str) -> Option<MessageKind> {
    if content.is_empty() {
        return None;
    }

    if matches!(
        event_type,
        "error"
            | "cli_error"
            | "tool_call"
            | "tool_result"
            | "cli_stats"
            | "token_usage"
            | "start"
            | "done"
            | "stream_end"
    ) {
        return None;
    }

    if matches!(
        event_type,
        "thinking" | "reasoning_content" | "task_analysis" | "analysis" | "plan" | "observation"
    ) {
        return Some(MessageKind::Process);
    }

    if matches!(
        event_type,
        "text" | "assistant" | "message" | "do_subtask_result"
    ) || matches!(role, "assistant" | "agent")
    {
        return Some(MessageKind::Assistant);
    }

    None
}

fn summarize_tool_event(names: &[String], content: &str) -> String {
    if !names.is_empty() {
        return names.join(", ");
    }

    truncate(&clean_single_line(content), 140)
}

fn clean_single_line(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn collect_tool_names(value: &Value) -> Vec<String> {
    let mut names = Vec::new();
    if let Some(tool_calls) = value.get("tool_calls").and_then(Value::as_array) {
        for tool_call in tool_calls {
            if let Some(name) = tool_call
                .get("function")
                .and_then(Value::as_object)
                .and_then(|function| function.get("name"))
                .and_then(Value::as_str)
            {
                names.push(name.to_string());
            }
        }
    }

    if let Some(metadata_name) = value
        .get("metadata")
        .and_then(Value::as_object)
        .and_then(|metadata| metadata.get("tool_name"))
        .and_then(Value::as_str)
    {
        names.push(metadata_name.to_string());
    }

    if let Some(event_name) = value.get("tool_name").and_then(Value::as_str) {
        names.push(event_name.to_string());
    }

    names.sort();
    names.dedup();
    names
}

fn truncate(text: &str, max_len: usize) -> String {
    if text.chars().count() <= max_len {
        return text.to_string();
    }
    text.chars()
        .take(max_len.saturating_sub(3))
        .collect::<String>()
        + "..."
}

#[cfg(test)]
mod tests {
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
}
