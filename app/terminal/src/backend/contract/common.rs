use anyhow::{anyhow, Result};
use serde_json::Value;

pub(crate) fn expect_array_field<'a>(
    value: &'a Value,
    key: &str,
    context: &str,
) -> Result<&'a [Value]> {
    value
        .get(key)
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .ok_or_else(|| anyhow!("{context} contract error: expected `{key}` array"))
}

pub(crate) fn expect_object_field<'a>(
    value: &'a Value,
    key: &str,
    context: &str,
) -> Result<&'a Value> {
    value
        .get(key)
        .and_then(Value::as_object)
        .map(|_| value.get(key).expect("field exists"))
        .ok_or_else(|| anyhow!("{context} contract error: expected `{key}` object"))
}

pub(crate) fn required_str_field<'a>(
    value: &'a Value,
    key: &str,
    context: &str,
) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("{context} contract error: expected `{key}` string"))
}

pub(crate) fn optional_str_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(ToString::to_string)
}

pub(crate) fn optional_u64_field(value: &Value, key: &str) -> u64 {
    value.get(key).and_then(Value::as_u64).unwrap_or(0)
}

pub(crate) fn optional_bool_field(value: &Value, key: &str) -> bool {
    value.get(key).and_then(Value::as_bool).unwrap_or(false)
}
