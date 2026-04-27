mod common;
mod config;
mod doctor;
mod providers;
mod sessions;
mod skills;
mod stream;

use anyhow::{anyhow, Result};
use serde_json::Value;
use std::path::Path;

use crate::backend::runtime::run_cli_json_owned;
use crate::backend::ProviderMutation;
pub(crate) use common::{
    expect_array_field, expect_object_field, optional_bool_field, optional_str_field,
    optional_u64_field, required_str_field,
};
pub(crate) use stream::{parse_stream_event, CliStreamEvent};

pub(crate) enum CliJsonCommand<'a> {
    ConfigShow,
    ConfigInit {
        path: Option<&'a str>,
        force: bool,
    },
    Doctor {
        probe_provider: bool,
    },
    SessionsList {
        user_id: &'a str,
        limit: usize,
    },
    SessionInspect {
        session_id: &'a str,
        user_id: &'a str,
    },
    SkillsList {
        user_id: &'a str,
        workspace: Option<&'a Path>,
    },
    ProvidersList {
        user_id: &'a str,
    },
    ProviderInspect {
        user_id: &'a str,
        provider_id: &'a str,
    },
    ProviderVerify {
        mutation: &'a ProviderMutation,
    },
    ProviderSetDefault {
        user_id: &'a str,
        provider_id: &'a str,
    },
    ProviderCreate {
        user_id: &'a str,
        mutation: &'a ProviderMutation,
    },
    ProviderUpdate {
        user_id: &'a str,
        provider_id: &'a str,
        mutation: &'a ProviderMutation,
    },
    ProviderDelete {
        user_id: &'a str,
        provider_id: &'a str,
    },
}

impl CliJsonCommand<'_> {
    fn label(&self) -> &'static str {
        match self {
            Self::ConfigShow => "config.show",
            Self::ConfigInit { .. } => "config.init",
            Self::Doctor { .. } => "doctor",
            Self::SessionsList { .. } => "sessions.list",
            Self::SessionInspect { .. } => "sessions.inspect",
            Self::SkillsList { .. } => "skills.list",
            Self::ProvidersList { .. } => "provider.list",
            Self::ProviderInspect { .. } => "provider.inspect",
            Self::ProviderVerify { .. } => "provider.verify",
            Self::ProviderSetDefault { .. } => "provider.set_default",
            Self::ProviderCreate { .. } => "provider.create",
            Self::ProviderUpdate { .. } => "provider.update",
            Self::ProviderDelete { .. } => "provider.delete",
        }
    }

    pub(crate) fn args(&self) -> Vec<String> {
        match self {
            Self::ConfigShow => config::config_show_args(),
            Self::ConfigInit { path, force } => config::config_init_args(*path, *force),
            Self::Doctor { probe_provider } => doctor::doctor_args(*probe_provider),
            Self::SessionsList { user_id, limit } => sessions::sessions_list_args(user_id, *limit),
            Self::SessionInspect {
                session_id,
                user_id,
            } => sessions::session_inspect_args(session_id, user_id),
            Self::SkillsList { user_id, workspace } => {
                skills::skills_list_args(user_id, *workspace)
            }
            Self::ProvidersList { user_id } => providers::providers_list_args(user_id),
            Self::ProviderInspect {
                user_id,
                provider_id,
            } => providers::provider_inspect_args(user_id, provider_id),
            Self::ProviderVerify { mutation } => providers::provider_verify_args(mutation),
            Self::ProviderSetDefault {
                user_id,
                provider_id,
            } => providers::provider_set_default_args(user_id, provider_id),
            Self::ProviderCreate { user_id, mutation } => {
                providers::provider_create_args(user_id, mutation)
            }
            Self::ProviderUpdate {
                user_id,
                provider_id,
                mutation,
            } => providers::provider_update_args(user_id, provider_id, mutation),
            Self::ProviderDelete {
                user_id,
                provider_id,
            } => providers::provider_delete_args(user_id, provider_id),
        }
    }
}

pub(crate) fn run_cli_command(command: CliJsonCommand<'_>) -> Result<Value> {
    let label = command.label();
    let args = command.args();
    run_cli_json_owned(&args).map_err(|err| anyhow!("{} failed: {err}", label))
}
