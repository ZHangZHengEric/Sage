use std::path::Path;

use anyhow::Result;

use crate::backend::contract::{
    expect_array_field, optional_str_field, run_cli_command, CliJsonCommand,
};
use crate::backend::SkillInfo;

pub(crate) fn list_skills(
    user_id: &str,
    agent_id: Option<&str>,
    workspace: Option<&Path>,
) -> Result<Vec<SkillInfo>> {
    let value = run_cli_command(CliJsonCommand::SkillsList {
        user_id,
        agent_id,
        workspace,
    })?;
    let items = expect_array_field(&value, "list", "skills.list")?;

    Ok(items
        .iter()
        .map(|item| SkillInfo {
            name: optional_str_field(item, "name").unwrap_or_default(),
            description: optional_str_field(item, "description").unwrap_or_default(),
            source: optional_str_field(item, "source").unwrap_or_else(|| "unknown".to_string()),
        })
        .collect())
}
