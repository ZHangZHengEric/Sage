use anyhow::Result;

use crate::backend::contract::{
    expect_array_field, optional_bool_field, optional_str_field, run_cli_command, CliJsonCommand,
};
use crate::backend::{ConfigInfo, ConfigInitInfo};

pub(crate) fn read_config() -> Result<ConfigInfo> {
    let value = run_cli_command(CliJsonCommand::ConfigShow)?;
    Ok(ConfigInfo {
        default_model_name: optional_str_field(&value, "default_llm_model_name")
            .unwrap_or_default(),
        default_api_base_url: optional_str_field(&value, "default_llm_api_base_url")
            .unwrap_or_default(),
        default_user_id: optional_str_field(&value, "default_cli_user_id").unwrap_or_default(),
        env_file: optional_str_field(&value, "env_file").unwrap_or_default(),
    })
}

pub(crate) fn init_config(path: Option<&str>, force: bool) -> Result<ConfigInitInfo> {
    let value = run_cli_command(CliJsonCommand::ConfigInit { path, force })?;
    let next_steps = expect_array_field(&value, "next_steps", "config.init")?
        .iter()
        .filter_map(|item| item.as_str().map(ToString::to_string))
        .collect::<Vec<_>>();

    Ok(ConfigInitInfo {
        path: optional_str_field(&value, "path").unwrap_or_default(),
        template: optional_str_field(&value, "template").unwrap_or_default(),
        overwritten: optional_bool_field(&value, "overwritten"),
        next_steps,
    })
}
