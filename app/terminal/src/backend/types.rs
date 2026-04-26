use std::path::PathBuf;

use crate::app::MessageKind;

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
