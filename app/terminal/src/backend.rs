#[path = "backend/api.rs"]
mod api;
#[path = "backend/handle.rs"]
mod handle;
#[path = "backend/protocol.rs"]
mod protocol;
#[cfg(test)]
#[path = "backend/tests.rs"]
mod tests;
#[path = "backend/types.rs"]
mod types;

pub(crate) use api::{
    create_provider, delete_provider, inspect_latest_session, inspect_provider, inspect_session,
    list_providers, list_sessions, list_skills, read_config, set_default_provider, update_provider,
};
pub(crate) use handle::BackendHandle;
pub use types::{
    BackendEvent, BackendRequest, ConfigInfo, ProviderInfo, ProviderMutation, SessionDetail,
    SessionMessage, SessionSummary, SkillInfo,
};
