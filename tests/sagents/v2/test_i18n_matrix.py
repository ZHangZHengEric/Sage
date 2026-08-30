from __future__ import annotations

import pytest

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.i18n import (
    _EN,
    _TRANSLATIONS,
    SUPPORTED_LANGUAGES,
    error_recovery_payload,
    localize_error,
    normalize_language,
    recovery_payload,
    tr,
)


def test_every_locale_defines_every_fixed_runtime_message():
    expected = set(_EN)
    for language in SUPPORTED_LANGUAGES:
        assert set(_TRANSLATIONS[language]) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("zh-CN", "zh"),
        ("en-US", "en"),
        ("pt-BR", "pt"),
        ("es-MX", "es"),
        ("fr-FR", "fr"),
        ("de-DE", "de"),
        ("ja-JP", "ja"),
        ("ko-KR", "ko"),
        ("ru-RU", "ru"),
        ("unsupported", "en"),
    ],
)
def test_runtime_language_normalization(raw, expected):
    assert normalize_language(raw) == expected


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_recovery_questionnaire_is_complete_in_every_supported_language(language):
    payload = recovery_payload(
        "recovery.max_steps", language, reason_code="budget.max_steps"
    )

    assert payload["language"] == language
    assert payload["title"]
    assert payload["prompt"]
    assert payload["guidance"]
    assert payload["questions"][0]["title"]
    assert payload["questions"][0]["placeholder"]
    assert payload["message_key"] == "recovery.max_steps"
    if language != "en":
        assert payload["title"] != tr("recovery.title", "en")
        assert payload["prompt"] != tr("recovery.max_steps", "en")


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
@pytest.mark.parametrize(
    "key",
    [
        "error.validation",
        "error.conflict",
        "error.policy_denied",
        "error.authentication",
        "error.authorization",
        "error.rate_limited",
        "error.provider_transient",
        "error.provider_permanent",
        "error.resource_lost",
        "error.unsupported_schema",
        "error.corrupt_state",
        "error.uncertain_side_effect",
        "error.cancelled",
        "error.internal",
        "error.model.stream_incomplete",
        "error.model.provider_error",
        "error.tool.provider_error",
        "error.tool.not_found",
        "error.tool.arguments_invalid",
        "error.tool.declined",
        "error.budget.max_tokens",
        "error.budget.deadline",
        "error.agent.driver_crashed",
        "error.agent.child_suspended",
        "error.flow.node_not_found",
        "error.flow.visit_budget_exhausted",
        "error.flow.node_failed",
        "questionnaire.invalid_list",
        "questionnaire.invalid_object",
        "questionnaire.invalid_type",
        "questionnaire.missing_title",
        "questionnaire.missing_options",
        "approval.title",
        "approval.tool_prompt",
        "approval.guidance",
        "approval.risk",
        "recovery.uncertain_tool",
        "goal.create_instruction",
        "goal.verify_instruction",
        "goal.explanation_required",
        "goal.complete_reason",
        "goal.create_required",
        "goal.incomplete",
        "plan.submitted_instruction",
        "plan.explanation_required",
        "plan.submitted_reason",
        "plan.required",
        "tool_selection.index_instruction",
    ],
)
def test_every_fixed_error_and_validation_key_resolves_for_every_locale(language, key):
    value = tr(key, language, index=1, tool="write_file")
    assert value
    assert value != key
    if language != "en":
        assert value != tr(key, "en", index=1, tool="write_file")


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_localized_errors_keep_raw_diagnostics_out_of_user_message(language):
    localized = localize_error(
        RuntimeErrorInfo(
            code="provider.secret_failure",
            category=ErrorCategory.INTERNAL,
            message="raw provider diagnostic with implementation details",
        ),
        language,
    )

    assert localized.message == tr("error.internal", language)
    assert localized.message_key == "error.internal"
    assert localized.metadata["diagnostic_message"].startswith("raw provider")
    assert localized.metadata["response_language"] == language


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_error_recovery_questionnaire_localizes_actions_and_guidance(language):
    error = localize_error(
        RuntimeErrorInfo(
            code="model.provider_error",
            category=ErrorCategory.PROVIDER_TRANSIENT,
            message="raw diagnostic",
            retryable=True,
        ),
        language,
    )

    payload = error_recovery_payload(error, language, resumable=True)

    assert payload["language"] == language
    assert payload["prompt"] == error.message
    assert payload["resumable"] is True
    assert [value["value"] for value in payload["questions"][0]["options"]] == [
        "retry",
        "change_direction",
        "cancel",
    ]
    if language != "en":
        assert payload["questions"][0]["options"][0]["label"] != tr(
            "action.retry", "en"
        )
