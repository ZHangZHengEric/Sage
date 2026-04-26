use anyhow::Result;

use crate::backend::ConfigInfo;
use crate::backend_support::run_cli_json;

pub(crate) fn read_config() -> Result<ConfigInfo> {
    let value = run_cli_json(&["config", "show", "--json"])?;
    Ok(ConfigInfo {
        default_model_name: value
            .get("default_llm_model_name")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        default_api_base_url: value
            .get("default_llm_api_base_url")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        default_user_id: value
            .get("default_cli_user_id")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
        env_file: value
            .get("env_file")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_string(),
    })
}
