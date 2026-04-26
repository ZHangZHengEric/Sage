use anyhow::{anyhow, Result};

use crate::backend::ProviderMutation;

pub(crate) fn parse_provider_mutation(
    fields: &[String],
    require_core_fields: bool,
) -> Result<ProviderMutation> {
    let mut mutation = ProviderMutation {
        name: None,
        base_url: None,
        api_key: None,
        model: None,
        is_default: None,
    };

    for field in fields {
        let (raw_key, raw_value) = field
            .split_once('=')
            .ok_or_else(|| anyhow!("expected key=value field, got `{field}`"))?;
        let key = raw_key.trim();
        let value = raw_value.trim();
        match key {
            "name" => assign_provider_field(&mut mutation.name, "name", value)?,
            "base" | "base_url" => assign_provider_field(&mut mutation.base_url, "base", value)?,
            "key" | "api_key" => assign_provider_field(&mut mutation.api_key, "key", value)?,
            "model" => assign_provider_field(&mut mutation.model, "model", value)?,
            "default" => {
                if mutation.is_default.is_some() {
                    return Err(anyhow!(
                        "duplicate provider field `default`; supply it once"
                    ));
                }
                mutation.is_default = Some(parse_provider_bool(value)?);
            }
            other => {
                return Err(anyhow!(
                    "unknown provider field `{other}`; use name= model= base= key= default=true|false"
                ));
            }
        }
    }

    if require_core_fields {
        let mut missing = Vec::new();
        if mutation.name.is_none() {
            missing.push("name");
        }
        if mutation.model.is_none() {
            missing.push("model");
        }
        if mutation.base_url.is_none() {
            missing.push("base");
        }
        if !missing.is_empty() {
            return Err(anyhow!(
                "provider create requires name=..., model=..., base=...; missing: {}",
                missing.join(", ")
            ));
        }
    }

    if !require_core_fields
        && mutation.name.is_none()
        && mutation.model.is_none()
        && mutation.base_url.is_none()
        && mutation.api_key.is_none()
        && mutation.is_default.is_none()
    {
        return Err(anyhow!(
            "provider update requires at least one key=value field"
        ));
    }

    Ok(mutation)
}

fn assign_provider_field(slot: &mut Option<String>, field_name: &str, value: &str) -> Result<()> {
    if slot.is_some() {
        return Err(anyhow!(
            "duplicate provider field `{field_name}`; supply it once"
        ));
    }
    if value.is_empty() {
        return Err(anyhow!("provider field `{field_name}` cannot be empty"));
    }
    *slot = Some(value.to_string());
    Ok(())
}

fn parse_provider_bool(value: &str) -> Result<bool> {
    match value {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => Err(anyhow!(
            "invalid default value `{value}`; use true/false, yes/no, on/off, or 1/0"
        )),
    }
}
