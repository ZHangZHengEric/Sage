use anyhow::Result;

use crate::backend::contract::{expect_array_field, optional_bool_field, optional_str_field, run_cli_command, CliJsonCommand};
use crate::backend::AgentInfo;

pub(crate) fn list_agents(user_id: &str) -> Result<Vec<AgentInfo>> {
    let value = run_cli_command(CliJsonCommand::AgentsList { user_id })?;
    let items = expect_array_field(&value, "list", "agents.list")?;
    Ok(items.iter().map(parse_agent).collect())
}

fn parse_agent(value: &serde_json::Value) -> AgentInfo {
    AgentInfo {
        agent_id: optional_str_field(value, "agent_id").unwrap_or_default(),
        name: optional_str_field(value, "name").unwrap_or_default(),
        agent_mode: optional_str_field(value, "agent_mode")
            .unwrap_or_else(|| "simple".to_string()),
        is_default: optional_bool_field(value, "is_default"),
        updated_at: optional_str_field(value, "updated_at").unwrap_or_default(),
    }
}
