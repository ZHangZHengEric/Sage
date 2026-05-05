use std::path::PathBuf;

use crate::app::MessageKind;

pub struct SessionSummary {
    pub session_id: String,
    pub title: String,
    pub message_count: u64,
    pub updated_at: String,
    pub last_preview: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BackendGoal {
    pub objective: String,
    pub status: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BackendGoalTransition {
    pub transition_type: String,
    pub objective: Option<String>,
    pub status: Option<String>,
    pub previous_objective: Option<String>,
    pub previous_status: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BackendSessionMeta {
    pub session_id: String,
    pub command_mode: Option<String>,
    pub session_state: Option<String>,
    pub goal: Option<BackendGoal>,
    pub goal_transition: Option<BackendGoalTransition>,
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

pub struct AgentInfo {
    pub agent_id: String,
    pub name: String,
    pub agent_mode: String,
    pub is_default: bool,
    pub updated_at: String,
}

pub struct ConfigInfo {
    pub default_model_name: String,
    pub default_api_base_url: String,
    pub default_user_id: String,
    pub env_file: String,
}

pub struct ConfigInitInfo {
    pub path: String,
    pub template: String,
    pub overwritten: bool,
    pub next_steps: Vec<String>,
}

pub struct ProviderInfo {
    pub id: String,
    pub name: String,
    pub model: String,
    pub base_url: String,
    pub is_default: bool,
    pub api_key_preview: String,
}

pub struct ProviderVerifyInfo {
    pub status: String,
    pub message: String,
    pub provider: ProviderInfo,
    pub sources: Vec<(String, String)>,
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
    pub agent_id: Option<String>,
    pub agent_mode: String,
    pub max_loop_count: u32,
    pub workspace: Option<PathBuf>,
    pub skills: Vec<String>,
    pub model_override: Option<String>,
    pub goal_objective: Option<String>,
    pub goal_status: Option<String>,
    pub clear_goal: bool,
    pub task: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BackendStats {
    pub elapsed_seconds: Option<f64>,
    pub first_output_seconds: Option<f64>,
    pub prompt_tokens: Option<u64>,
    pub completion_tokens: Option<u64>,
    pub total_tokens: Option<u64>,
    pub tool_steps: Vec<BackendToolStep>,
    pub phase_timings: Vec<BackendPhaseTiming>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BackendToolStep {
    pub step: u64,
    pub tool_name: String,
    pub tool_call_id: Option<String>,
    pub status: String,
    pub started_at: Option<f64>,
    pub finished_at: Option<f64>,
    pub duration_ms: Option<f64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct BackendPhaseTiming {
    pub phase: String,
    pub started_at: Option<f64>,
    pub finished_at: Option<f64>,
    pub duration_ms: Option<f64>,
    pub segment_count: u64,
}

pub enum BackendEvent {
    SessionHydrated(BackendSessionMeta),
    LiveChunk(MessageKind, String),
    Message(MessageKind, String),
    Status(String),
    PhaseChanged(String),
    ToolStarted(String),
    ToolFinished(String),
    Stats(BackendStats),
    Error(String),
    Finished,
    Exited,
}
