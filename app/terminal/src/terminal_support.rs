#[path = "terminal/context.rs"]
mod context;
#[path = "terminal/formatting.rs"]
mod formatting;
#[path = "terminal/provider_args.rs"]
mod provider_args;

pub(crate) use context::{apply_resumed_session, sync_contextual_popup_data, workspace_root};
pub(crate) use formatting::{
    format_agents_list, format_config, format_config_init, format_doctor_info,
    format_provider_detail, format_provider_verify, format_providers, format_session_detail,
    format_skills_list,
};
pub(crate) use provider_args::{parse_provider_mutation, parse_provider_mutation_allow_empty};
