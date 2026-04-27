mod api;
pub(crate) mod contract;
mod handle;
mod protocol;
pub(crate) mod runtime;
#[cfg(test)]
mod tests;
mod types;

pub(crate) use api::{
    create_provider, delete_provider, init_config, inspect_latest_session, inspect_provider,
    inspect_session, list_providers, list_sessions, list_skills, read_config, read_doctor_info,
    set_default_provider, update_provider, verify_provider,
};
pub(crate) use handle::BackendHandle;
pub use types::{
    BackendEvent, BackendRequest, ConfigInfo, ConfigInitInfo, ProviderInfo, ProviderMutation,
    ProviderVerifyInfo, SessionDetail, SessionMessage, SessionSummary, SkillInfo,
};
