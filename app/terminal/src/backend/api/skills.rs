use std::path::Path;

use anyhow::Result;
use serde_json::Value;

use crate::backend::SkillInfo;
use crate::backend_support::run_cli_json;

pub(crate) fn list_skills(user_id: &str, workspace: Option<&Path>) -> Result<Vec<SkillInfo>> {
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
