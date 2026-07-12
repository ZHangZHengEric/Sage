from sagents.prompts.agent_base_prompts import agent_intro_template


def test_health_workspace_protocol_is_conditional_and_safe_in_all_languages() -> None:
    for language in ("zh", "en", "pt"):
        prompt = agent_intro_template[language]
        assert "health_workspace.available=true" in prompt
        assert "README" in prompt
        assert "Workout" in prompt


def test_english_health_workspace_protocol_preserves_sparse_and_medical_boundaries() -> None:
    prompt = agent_intro_template["en"]
    assert "Missing rows and empty fields" in prompt
    assert "never zero" in prompt
    assert "Do not diagnose" in prompt
    assert "Do not expose stable internal keys" in prompt
