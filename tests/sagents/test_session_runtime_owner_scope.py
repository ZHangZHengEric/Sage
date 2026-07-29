from sagents.session_runtime import SessionManager


def test_session_manager_isolates_live_sessions_by_runtime_owner(tmp_path):
    manager = SessionManager(str(tmp_path), enable_obs=False)

    owner_a = manager.get_or_create(
        "shared-session",
        runtime_owner_id="owner-a",
    )
    owner_b = manager.get_or_create(
        "shared-session",
        runtime_owner_id="owner-b",
    )
    unscoped = manager.get_or_create("shared-session")

    assert owner_a is not owner_b
    assert owner_a is not unscoped
    assert owner_b is not unscoped
    assert owner_a.session_id == "shared-session"
    assert owner_b.session_id == "shared-session"
    assert manager.get_live_session(
        "shared-session", runtime_owner_id="owner-a"
    ) is owner_a
    assert manager.get_live_session(
        "shared-session", runtime_owner_id="owner-b"
    ) is owner_b
    assert manager.get_live_session("shared-session") is unscoped


def test_closing_one_runtime_owner_does_not_close_other_owner(tmp_path):
    manager = SessionManager(str(tmp_path), enable_obs=False)
    owner_a = manager.get_or_create(
        "shared-session",
        runtime_owner_id="owner-a",
    )
    owner_b = manager.get_or_create(
        "shared-session",
        runtime_owner_id="owner-b",
    )

    manager.close_session("shared-session", runtime_owner_id="owner-a")

    assert (
        manager.get_live_session(
            "shared-session", runtime_owner_id="owner-a"
        )
        is None
    )
    assert manager.get_live_session(
        "shared-session", runtime_owner_id="owner-b"
    ) is owner_b
    assert owner_a is not owner_b
