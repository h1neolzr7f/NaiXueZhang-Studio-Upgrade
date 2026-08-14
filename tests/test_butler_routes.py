from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch
import base64

from tests.asgi_client import TestClient

import server
from routes import butler as butler_routes


class ButlerRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(server.app)

    def test_page_and_status_are_reachable(self) -> None:
        page = self.client.get("/butler")
        self.assertEqual(page.status_code, 200)
        self.assertIn("text/html", page.headers.get("content-type", ""))
        status = self.client.get("/api/butler/status")
        self.assertEqual(status.status_code, 200)
        self.assertIn("skills", status.json())

    def test_chat_route_returns_typed_plan_response(self) -> None:
        payload = {"ok": True, "reply": "ok", "tool_results": [], "pending_actions": []}
        with patch(
            "routes.butler.submit_butler_chat",
            new=AsyncMock(return_value=payload),
        ) as run:
            response = self.client.post("/api/butler/chat", json={"message": "找图", "history": []})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "ok")
        run.assert_awaited_once_with("找图", [], None, "")

    def test_chat_route_forwards_a_valid_ephemeral_image_attachment(self) -> None:
        payload = {"ok": True, "reply": "看到了", "tool_results": [], "pending_actions": []}
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode("ascii")
        image = {
            "name": "preview.png",
            "mime": "image/png",
            "data_url": f"data:image/png;base64,{png}",
        }
        with patch(
            "routes.butler.submit_butler_chat",
            new=AsyncMock(return_value=payload),
        ) as run:
            response = self.client.post(
                "/api/butler/chat",
                json={"message": "评价这张图", "history": [], "image": image},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "看到了")
        run.assert_awaited_once_with("评价这张图", [], image, "")

    def test_gallery_audit_intent_is_forwarded_without_client_tool_arguments(self) -> None:
        payload = {"ok": True, "reply": "开始体检", "tool_results": []}
        with patch(
            "routes.butler.submit_butler_chat",
            new=AsyncMock(return_value=payload),
        ) as run:
            response = self.client.post(
                "/api/butler/chat",
                json={"message": "体检图库", "history": [], "intent": "gallery_audit"},
            )
        self.assertEqual(response.status_code, 200)
        run.assert_awaited_once_with("体检图库", [], None, "gallery_audit")

    def test_chat_route_forwards_selected_agent(self) -> None:
        payload = {"ok": True, "reply": "ok", "tool_results": [], "pending_actions": []}
        with patch(
            "routes.butler.submit_butler_chat",
            new=AsyncMock(return_value=payload),
        ) as run:
            response = self.client.post(
                "/api/butler/chat",
                json={"message": "找图", "history": [], "agent": "tomori"},
            )
        self.assertEqual(response.status_code, 200)
        run.assert_awaited_once_with("找图", [], None, "", agent="tomori")

    def test_butler_templates_can_be_listed_and_saved_without_execution(self) -> None:
        templates = [{"id": "builtin-local-audit", "label": "零 Token 图库体检"}]
        saved = {"id": "user-1", "label": "我的任务", "prompt": "检查队列"}
        with patch("routes.butler.TEMPLATES.list_all", return_value=templates), patch(
            "routes.butler.TEMPLATES.save", return_value=saved
        ) as save, patch("routes.butler.submit_butler_chat") as submit:
            listed = self.client.get("/api/butler/templates")
            created = self.client.post(
                "/api/butler/templates",
                json={"label": "我的任务", "prompt": "检查队列"},
            )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["template"], saved)
        save.assert_called_once_with(label="我的任务", prompt="检查队列")
        submit.assert_not_called()

    def test_software_help_answers_with_exact_page_and_cost_boundary(self) -> None:
        response = self.client.post(
            "/api/butler/help",
            json={"question": "怎么批量换画风，会不会识图和消耗 Token？"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["topic"], "remix")
        self.assertEqual(payload["page"], "/remix")
        self.assertIn("不会调用识图", payload["answer"])
        self.assertIn("确认生成后才会消耗 NAI", payload["answer"])

    def test_software_help_exposes_batch_director_as_a_standalone_feature(self) -> None:
        response = self.client.post(
            "/api/butler/help",
            json={"question": "NAI 批量导演在哪里，预览会不会扣费？"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["topic"], "director")
        self.assertEqual(payload["page"], "/director")
        self.assertIn("预览不会请求 NAI", payload["answer"])
        self.assertIn("计费确认", payload["answer"])

    def test_unconfigured_ai_maps_to_conflict(self) -> None:
        with patch(
            "routes.butler.submit_butler_chat",
            new=AsyncMock(side_effect=RuntimeError("未配置")),
        ):
            response = self.client.post("/api/butler/chat", json={"message": "找图"})
        self.assertEqual(response.status_code, 409)

    def test_confirmation_route_never_accepts_client_action_json(self) -> None:
        with patch(
            "routes.butler.confirm_butler_action",
            new=AsyncMock(return_value={"ok": True, "cancelled": False}),
        ) as confirm:
            response = self.client.post(
                "/api/butler/confirm",
                json={
                    "confirmation_id": "server-ticket",
                    "approve": True,
                    "tool": "shell",
                    "arguments": {"command": "ignored"},
                },
            )
        self.assertEqual(response.status_code, 200)
        confirm.assert_awaited_once_with("server-ticket", approve=True)

    def test_task_center_routes_use_server_side_workflow_ids(self) -> None:
        task = {"id": "wf-1", "status": "running", "events": []}
        with patch(
            "routes.butler.list_butler_tasks", return_value={"ok": True, "tasks": [task]}
        ), patch(
            "routes.butler.get_butler_task", return_value={"ok": True, "task": task}
        ), patch(
            "routes.butler.cancel_butler_task",
            new=AsyncMock(return_value={"ok": True, "task": task}),
        ) as cancel:
            listed = self.client.get("/api/butler/tasks")
            detail = self.client.get("/api/butler/tasks/wf-1")
            stopped = self.client.post("/api/butler/tasks/wf-1/cancel", json={"tool": "shell"})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(detail.json()["task"]["id"], "wf-1")
        self.assertEqual(stopped.status_code, 200)
        cancel.assert_awaited_once_with("wf-1")

    def test_task_list_can_include_selected_detail_in_one_round_trip(self) -> None:
        summary = {"id": "wf-1", "status": "running"}
        detail = {**summary, "events": [{"type": "created"}]}
        with patch(
            "routes.butler.list_butler_tasks", return_value={"ok": True, "tasks": [summary]}
        ) as listed, patch(
            "routes.butler.get_butler_task", return_value={"ok": True, "task": detail}
        ) as selected:
            response = self.client.get("/api/butler/tasks?limit=20&selected_id=wf-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["selected_task"]["events"][0]["type"], "created")
        listed.assert_called_once_with(limit=20, status="")
        selected.assert_called_once_with("wf-1")

    def test_task_list_keeps_reports_in_detail_and_sends_only_summary_rows(self) -> None:
        task = {
            "id": "wf-heavy",
            "status": "succeeded",
            "terminal": True,
            "title": "批量任务",
            "progress": {"current": 20, "total": 20},
            "input": {"large": "x" * 20000},
            "result": {
                "report": {"summary": "done", "large": "y" * 20000},
                "gallery_url": "/generated",
            },
        }
        with patch(
            "routes.butler.list_butler_tasks",
            return_value={"ok": True, "tasks": [task]},
        ), patch(
            "routes.butler.get_butler_task",
            return_value={"ok": True, "task": task},
        ):
            listed = self.client.get("/api/butler/tasks")
            detail = self.client.get("/api/butler/tasks/wf-heavy")

        summary = listed.json()["tasks"][0]
        self.assertTrue(summary["has_report"])
        self.assertEqual(summary["result_summary"]["gallery_url"], "/generated")
        self.assertNotIn("input", summary)
        self.assertNotIn("result", summary)
        self.assertIn("result", detail.json()["task"])

    def test_task_center_exposes_server_sent_event_stream(self) -> None:
        route = next(
            (item for item in server.app.routes if item.path == "/api/butler/tasks/stream"),
            None,
        )
        self.assertIsNotNone(route)
        self.assertIn("GET", route.methods)

    def test_task_event_stream_sends_an_immediate_selected_snapshot(self) -> None:
        summary = {"id": "wf-push", "status": "running"}
        detail = {**summary, "events": [{"type": "started"}]}

        async def first_event():
            request = type("RequestStub", (), {"is_disconnected": AsyncMock(return_value=False)})()
            response = await butler_routes.api_butler_task_stream(
                request,
                selected_id="wf-push",
            )
            chunk = await anext(response.body_iterator)
            await response.body_iterator.aclose()
            return response, chunk

        with patch("routes.butler.butler_task_revision", return_value=7), patch(
            "routes.butler.list_butler_tasks",
            return_value={"ok": True, "tasks": [summary]},
        ), patch(
            "routes.butler.get_butler_task",
            return_value={"ok": True, "task": detail},
        ):
            response, chunk = asyncio.run(first_event())

        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
        data_line = next(line for line in text.splitlines() if line.startswith("data: "))
        payload = json.loads(data_line.removeprefix("data: "))
        self.assertEqual(response.media_type, "text/event-stream")
        self.assertIn("event: tasks", text)
        self.assertEqual(payload["revision"], 7)
        self.assertEqual(payload["selected_task"]["events"][0]["type"], "started")

    def test_chat_history_can_be_loaded_and_explicitly_cleared(self) -> None:
        messages = [{"id": 1, "role": "user", "content": "你好，小镜"}]
        with patch(
            "routes.butler.list_butler_messages",
            return_value={"ok": True, "messages": messages},
        ) as listed, patch(
            "routes.butler.clear_butler_messages",
            return_value={"ok": True, "deleted": 1},
        ) as cleared:
            history = self.client.get("/api/butler/history?limit=60")
            removed = self.client.delete("/api/butler/history")

        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["messages"], messages)
        self.assertEqual(removed.json()["deleted"], 1)
        listed.assert_called_once_with(limit=60, before_id=None)
        cleared.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
