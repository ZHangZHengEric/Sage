import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from common.core.exceptions import SageHTTPException
from common.schemas.goal import GoalStatus, SessionGoal
from common.services import conversation_service


class _FakeSession:
    def __init__(self):
        self.goal = None
        self.goal_transition = None

    def has_context(self):
        return True

    def set_goal(self, objective: str, status: GoalStatus = GoalStatus.ACTIVE):
        previous_goal = self.goal
        self.goal = SessionGoal(
            objective=objective,
            status=status,
            created_at=1.0,
            updated_at=2.0,
        )
        self.goal_transition = (
            {
                "type": "replaced",
                "objective": objective,
                "status": status.value,
                "previous_objective": previous_goal.objective,
                "previous_status": previous_goal.status.value,
            }
            if previous_goal
            else None
        )
        return self.goal

    def clear_goal(self):
        previous_goal = self.goal
        self.goal = None
        self.goal_transition = {
            "type": "cleared",
            "previous_objective": previous_goal.objective if previous_goal else None,
            "previous_status": previous_goal.status.value if previous_goal else None,
        }
        return True

    def get_goal(self):
        return self.goal

    def get_goal_transition(self):
        return self.goal_transition

    def complete_goal(self):
        if not self.goal:
            return None
        self.goal.status = GoalStatus.COMPLETED
        self.goal.completed_at = 3.0
        self.goal.updated_at = 3.0
        self.goal_transition = {
            "type": "completed",
            "objective": self.goal.objective,
            "status": self.goal.status.value,
        }
        return self.goal


class _FakeSessionManager:
    def __init__(self, *, session=None, goal=None):
        self.session = session
        self.goal = goal

    def get(self, session_id: str):
        return self.session

    def get_goal(self, session_id: str):
        return self.goal

    def get_goal_transition(self, session_id: str):
        if self.session and hasattr(self.session, "get_goal_transition"):
            return self.session.get_goal_transition()
        return None


class TestConversationGoalService(unittest.IsolatedAsyncioTestCase):
    async def test_set_session_goal_persists_and_returns_payload(self):
        conversation = SimpleNamespace(user_id="user-1")
        fake_session = _FakeSession()
        fake_manager = _FakeSessionManager(session=fake_session)

        with (
            patch.object(
                conversation_service.ConversationDao,
                "get_by_session_id",
                new=AsyncMock(return_value=conversation),
            ),
            patch.object(conversation_service, "get_global_session_manager", return_value=fake_manager),
            patch.object(conversation_service, "persist_session_state", new=AsyncMock()) as persist_mock,
        ):
            result = await conversation_service.set_session_goal(
                "session-1",
                objective="ship explicit service goal API",
                status=GoalStatus.ACTIVE,
                user_id="user-1",
            )

        self.assertEqual(result["session_id"], "session-1")
        self.assertEqual(result["goal"]["objective"], "ship explicit service goal API")
        self.assertEqual(result["goal"]["status"], "active")
        self.assertIsNone(result["goal_transition"])
        persist_mock.assert_awaited_once_with("session-1")

    async def test_clear_session_goal_persists_and_returns_none(self):
        conversation = SimpleNamespace(user_id="user-1")
        fake_session = _FakeSession()
        fake_session.set_goal("temp goal", GoalStatus.ACTIVE)
        fake_manager = _FakeSessionManager(session=fake_session)

        with (
            patch.object(
                conversation_service.ConversationDao,
                "get_by_session_id",
                new=AsyncMock(return_value=conversation),
            ),
            patch.object(conversation_service, "get_global_session_manager", return_value=fake_manager),
            patch.object(conversation_service, "persist_session_state", new=AsyncMock()) as persist_mock,
        ):
            result = await conversation_service.clear_session_goal(
                "session-1",
                user_id="user-1",
            )

        self.assertEqual(result["session_id"], "session-1")
        self.assertIsNone(result["goal"])
        self.assertEqual(result["goal_transition"]["type"], "cleared")
        persist_mock.assert_awaited_once_with("session-1")

    async def test_set_session_goal_returns_replace_transition_when_previous_goal_exists(self):
        conversation = SimpleNamespace(user_id="user-1")
        fake_session = _FakeSession()
        fake_session.set_goal("old goal", GoalStatus.ACTIVE)
        fake_manager = _FakeSessionManager(session=fake_session)

        with (
            patch.object(
                conversation_service.ConversationDao,
                "get_by_session_id",
                new=AsyncMock(return_value=conversation),
            ),
            patch.object(conversation_service, "get_global_session_manager", return_value=fake_manager),
            patch.object(conversation_service, "persist_session_state", new=AsyncMock()) as persist_mock,
        ):
            result = await conversation_service.set_session_goal(
                "session-1",
                objective="replace goal",
                status=GoalStatus.ACTIVE,
                user_id="user-1",
            )

        self.assertEqual(result["goal"]["objective"], "replace goal")
        self.assertEqual(result["goal_transition"]["type"], "replaced")
        self.assertEqual(result["goal_transition"]["previous_objective"], "old goal")
        persist_mock.assert_awaited_once_with("session-1")

    async def test_complete_session_goal_requires_existing_goal(self):
        conversation = SimpleNamespace(user_id="user-1")
        fake_session = _FakeSession()
        fake_manager = _FakeSessionManager(session=fake_session)

        with (
            patch.object(
                conversation_service.ConversationDao,
                "get_by_session_id",
                new=AsyncMock(return_value=conversation),
            ),
            patch.object(conversation_service, "get_global_session_manager", return_value=fake_manager),
            patch.object(conversation_service, "_is_desktop_mode", return_value=False),
        ):
            with self.assertRaises(SageHTTPException) as ctx:
                await conversation_service.complete_session_goal(
                    "session-1",
                    user_id="user-1",
                )

        self.assertEqual(ctx.exception.detail, "当前会话没有可完成的目标")

    async def test_get_session_goal_returns_manager_goal(self):
        conversation = SimpleNamespace(user_id="user-1")
        goal = SessionGoal(
            objective="persisted goal",
            status=GoalStatus.PAUSED,
            created_at=1.0,
            updated_at=2.0,
            paused_reason="interrupted",
        )
        fake_manager = _FakeSessionManager(goal=goal)

        with (
            patch.object(
                conversation_service.ConversationDao,
                "get_by_session_id",
                new=AsyncMock(return_value=conversation),
            ),
            patch.object(conversation_service, "get_global_session_manager", return_value=fake_manager),
        ):
            result = await conversation_service.get_session_goal(
                "session-1",
                user_id="user-1",
            )

        self.assertEqual(result["session_id"], "session-1")
        self.assertEqual(result["goal"]["objective"], "persisted goal")
        self.assertEqual(result["goal"]["status"], "paused")
        self.assertIsNone(result["goal_transition"])

    async def test_get_conversations_paginated_filters_by_goal_status(self):
        conversations = [
            SimpleNamespace(session_id="session-active"),
            SimpleNamespace(session_id="session-paused"),
            SimpleNamespace(session_id="session-none"),
        ]
        goal_map = {
            "session-active": SessionGoal(
                objective="active goal",
                status=GoalStatus.ACTIVE,
                created_at=1.0,
                updated_at=2.0,
            ),
            "session-paused": SessionGoal(
                objective="paused goal",
                status=GoalStatus.PAUSED,
                created_at=1.0,
                updated_at=2.0,
                paused_reason="blocked",
            ),
        }

        with (
            patch.object(
                conversation_service.ConversationDao,
                "get_conversations_filtered",
                new=AsyncMock(return_value=conversations),
            ),
            patch.object(
                conversation_service,
                "_load_session_goal",
                side_effect=lambda session_id: goal_map.get(session_id),
            ),
        ):
            items, total = await conversation_service.get_conversations_paginated(
                page=1,
                page_size=10,
                goal_status="paused",
            )
            none_items, none_total = await conversation_service.get_conversations_paginated(
                page=1,
                page_size=10,
                goal_status="none",
            )

        self.assertEqual(total, 1)
        self.assertEqual([item.session_id for item in items], ["session-paused"])
        self.assertEqual(none_total, 1)
        self.assertEqual([item.session_id for item in none_items], ["session-none"])
