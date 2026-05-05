import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.server.routers.conversation import conversation_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(conversation_router)
    return app


class TestConversationGoalRoutes(unittest.TestCase):
    def test_list_conversations_route_forwards_goal_status(self):
        app = _build_app()

        with TestClient(app) as client:
            with patch(
                "app.server.routers.conversation.get_request_user_id",
                return_value="user-1",
            ), patch(
                "app.server.routers.conversation.get_request_role",
                return_value="user",
            ), patch(
                "common.services.conversation_router_service.build_list_conversations_response",
                new_callable=AsyncMock,
                return_value={"list": [], "total": 0},
            ) as mock_build:
                response = client.get("/api/conversations?goal_status=paused")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["total"], 0)
        self.assertEqual(mock_build.await_args.kwargs["goal_status"], "paused")

    def test_get_goal_route_uses_router_service(self):
        app = _build_app()

        with TestClient(app) as client:
            with patch(
                "app.server.routers.conversation.get_request_user_id",
                return_value="user-1",
            ), patch(
                "common.services.conversation_router_service.build_goal_status_response",
                new_callable=AsyncMock,
                return_value={
                    "message": "ok",
                    "data": {"session_id": "session-1", "goal": None},
                },
            ) as mock_build:
                response = client.get("/api/sessions/session-1/goal")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["session_id"], "session-1")
        mock_build.assert_awaited_once_with("session-1", user_id="user-1")

    def test_set_goal_route_forwards_objective_and_status(self):
        app = _build_app()

        with TestClient(app) as client:
            with patch(
                "app.server.routers.conversation.get_request_user_id",
                return_value="user-1",
            ), patch(
                "common.services.conversation_router_service.build_goal_set_response",
                new_callable=AsyncMock,
                return_value={
                    "message": "ok",
                    "data": {
                        "session_id": "session-1",
                        "goal": {"objective": "ship goal api", "status": "active"},
                    },
                },
            ) as mock_build:
                response = client.post(
                    "/api/sessions/session-1/goal",
                    json={"objective": "ship goal api", "status": "active"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["goal"]["objective"], "ship goal api")
        mock_build.assert_awaited_once()
        self.assertEqual(mock_build.await_args.kwargs["objective"], "ship goal api")
        self.assertEqual(mock_build.await_args.kwargs["status"].value, "active")
        self.assertEqual(mock_build.await_args.kwargs["user_id"], "user-1")

    def test_clear_goal_route_uses_router_service(self):
        app = _build_app()

        with TestClient(app) as client:
            with patch(
                "app.server.routers.conversation.get_request_user_id",
                return_value="user-1",
            ), patch(
                "common.services.conversation_router_service.build_goal_clear_response",
                new_callable=AsyncMock,
                return_value={
                    "message": "ok",
                    "data": {"session_id": "session-1", "goal": None},
                },
            ) as mock_build:
                response = client.delete("/api/sessions/session-1/goal")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertIsNone(payload["data"]["goal"])
        mock_build.assert_awaited_once_with("session-1", user_id="user-1")

    def test_complete_goal_route_uses_router_service(self):
        app = _build_app()

        with TestClient(app) as client:
            with patch(
                "app.server.routers.conversation.get_request_user_id",
                return_value="user-1",
            ), patch(
                "common.services.conversation_router_service.build_goal_complete_response",
                new_callable=AsyncMock,
                return_value={
                    "message": "ok",
                    "data": {
                        "session_id": "session-1",
                        "goal": {"objective": "ship goal api", "status": "completed"},
                    },
                },
            ) as mock_build:
                response = client.post("/api/sessions/session-1/goal/complete")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["goal"]["status"], "completed")
        mock_build.assert_awaited_once_with("session-1", user_id="user-1")
