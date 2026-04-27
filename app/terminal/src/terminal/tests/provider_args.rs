use crate::terminal_support::{parse_provider_mutation, parse_provider_mutation_allow_empty};

#[test]
fn parse_provider_mutation_rejects_invalid_default_flag() {
    let err = parse_provider_mutation(&[String::from("default=maybe")], false)
        .expect_err("default=maybe should fail");
    assert_eq!(
        err.to_string(),
        "invalid default value `maybe`; use true/false, yes/no, on/off, or 1/0"
    );
}

#[test]
fn parse_provider_mutation_rejects_duplicate_fields() {
    let err = parse_provider_mutation(
        &[String::from("model=alpha"), String::from("model=beta")],
        false,
    )
    .expect_err("duplicate model should fail");
    assert_eq!(
        err.to_string(),
        "duplicate provider field `model`; supply it once"
    );
}

#[test]
fn parse_provider_mutation_rejects_empty_values() {
    let err = parse_provider_mutation(&[String::from("name=")], false)
        .expect_err("empty values should fail");
    assert_eq!(err.to_string(), "provider field `name` cannot be empty");
}

#[test]
fn parse_provider_mutation_reports_missing_create_fields() {
    let err = parse_provider_mutation(
        &[
            String::from("name=demo"),
            String::from("base=https://example.com"),
        ],
        true,
    )
    .expect_err("missing model should fail");
    assert_eq!(
        err.to_string(),
        "provider create requires name=..., model=..., base=...; missing: model"
    );
}

#[test]
fn parse_provider_mutation_accepts_false_default_values() {
    let mutation = parse_provider_mutation(
        &[
            String::from("name=demo"),
            String::from("model=demo-chat"),
            String::from("base=https://example.com"),
            String::from("default=off"),
        ],
        true,
    )
    .expect("valid mutation should parse");
    assert_eq!(mutation.is_default, Some(false));
}

#[test]
fn parse_provider_mutation_allow_empty_supports_verify_against_default_env() {
    let mutation = parse_provider_mutation_allow_empty(&[], false)
        .expect("empty verify mutation should be allowed");
    assert!(mutation.name.is_none());
    assert!(mutation.model.is_none());
    assert!(mutation.base_url.is_none());
}
