"""HTTP contract tests for the FastAPI inspector."""

from __future__ import annotations

import json
import queue
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from xui_lab.inspector_http import (
    MAX_ACTION_BYTES,
    SECURITY_HEADERS,
    InspectorBusyError,
    InspectorWorker,
    create_inspector_app,
    format_sse_event,
    inspector_openapi_document,
    inspector_openapi_hash,
)

SESSION_TOKEN = "test-inspector-token"


class SessionStub:
    def __init__(self, capture: Path | None = None) -> None:
        self.latest_capture = capture
        self.closed = False
        self.action_delay = 0.0
        self.release = threading.Event()
        self.release.set()
        self.started = threading.Event()
        self.calls: list[dict[str, Any]] = []
        self.order: list[tuple[str, str]] = []
        self.state_value: dict[str, Any] = {
            "tree": {"control_id": "root", "path": "/root", "children": []},
            "diagnostics": {"processId": 7},
            "recording": [],
            "locators": {},
            "artifactDir": "/tmp/xui-lab-inspector",
            "subjects": ["test_widgets"],
            "fixtures": [],
            "scenarios": ["test_floater"],
            "inputOperations": ["click"],
            "capture": {
                "available": capture is not None,
                "version": 1 if capture is not None else 0,
            },
        }

    def capture_path(self, version: int) -> Path | None:
        if self.latest_capture is None or version != 1:
            return None
        return self.latest_capture

    def close(self) -> None:
        self.closed = True

    def action(self, request: dict[str, Any]) -> dict[str, Any]:
        kind = str(request.get("action", ""))
        self.order.append(("start", kind))
        self.started.set()
        self.release.wait(timeout=2)
        if self.action_delay:
            time.sleep(self.action_delay)
        self.calls.append(request)
        self.order.append(("end", kind))
        recording = self.state_value.get("recording")
        if isinstance(recording, list):
            self.state_value["recording"] = [*recording, kind]
        return {"accepted": True, "action": kind}

    def state(self) -> dict[str, Any]:
        return self.state_value


class InspectorHttpTests(unittest.TestCase):
    def client(self, session: SessionStub) -> TestClient:
        client = TestClient(
            create_inspector_app(InspectorWorker(session), session_token=SESSION_TOKEN)
        )
        client.cookies.set("xui_lab_session", SESSION_TOKEN)
        return client

    def test_index_issues_session_cookie_and_api_requires_it(self) -> None:
        app = create_inspector_app(
            InspectorWorker(SessionStub()), session_token=SESSION_TOKEN
        )
        with TestClient(app) as client:
            rejected = client.get("/api/v1/state")
            index = client.get("/")
            accepted = client.get("/api/v1/state")
        self.assertEqual(401, rejected.status_code)
        self.assertEqual("application/problem+json", rejected.headers["content-type"])
        self.assertEqual("invalid_session", rejected.json()["code"])
        self.assertEqual(401, rejected.json()["status"])
        self.assertEqual(
            "https://xui-lab.local/problems/invalid_session",
            rejected.json()["type"],
        )
        self.assertIn("HttpOnly", index.headers["set-cookie"])
        self.assertIn("SameSite=strict", index.headers["set-cookie"])
        self.assertEqual(200, accepted.status_code)

    def test_serves_the_built_react_client_with_security_headers(self) -> None:
        with self.client(SessionStub()) as client:
            response = client.get("/")
        self.assertEqual(200, response.status_code)
        self.assertEqual("text/html; charset=utf-8", response.headers["content-type"])
        self.assertIn('<div id="root"></div>', response.text)
        self.assertIn("/assets/app.js", response.text)
        for name, value in SECURITY_HEADERS.items():
            self.assertEqual(value, response.headers[name.lower()])

    def test_serves_fingerprint_stable_assets(self) -> None:
        with self.client(SessionStub()) as client:
            response = client.get("/assets/app.js")
        self.assertEqual(200, response.status_code)
        self.assertIn("javascript", response.headers["content-type"])

    def test_disables_docs_cors_and_legacy_routes(self) -> None:
        with self.client(SessionStub()) as client:
            self.assertEqual(404, client.get("/docs").status_code)
            self.assertEqual(404, client.get("/redoc").status_code)
            self.assertEqual(404, client.get("/openapi.json").status_code)
            self.assertEqual(404, client.get("/api/state").status_code)
            options = client.options("/api/v1/state")
        self.assertNotIn("access-control-allow-origin", options.headers)

    def test_state_is_an_immutable_snapshot(self) -> None:
        session = SessionStub()
        with self.client(session) as client:
            first = client.get("/api/v1/state")
            body = first.json()
            body["tree"]["injected"] = True
            session.state_value["tree"]["live"] = True
            second = client.get("/api/v1/state")
        self.assertEqual(200, first.status_code)
        self.assertEqual("root", first.json()["tree"]["control_id"])
        self.assertEqual(1, first.json()["stateVersion"])
        self.assertNotIn("injected", second.json()["tree"])
        self.assertTrue(second.json()["tree"]["live"])
        self.assertEqual(2, second.json()["stateVersion"])
        self.assertEqual(inspector_openapi_hash(), second.json()["openapiHash"])

    def test_unchanged_state_keeps_the_same_version(self) -> None:
        session = SessionStub()
        with self.client(session) as client:
            first = client.get("/api/v1/state")
            second = client.get("/api/v1/state")
        self.assertEqual(1, first.json()["stateVersion"])
        self.assertEqual(1, second.json()["stateVersion"])

    def test_actions_use_the_interactive_pydantic_models(self) -> None:
        session = SessionStub()
        with self.client(session) as client:
            response = client.post("/api/v1/actions", json={"action": "capture"})
            failure = client.post(
                "/api/v1/actions",
                json={"action": "pick", "x": "not-an-integer", "y": 20},
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"ok": True, "result": {"accepted": True, "action": "capture"}},
            response.json(),
        )
        self.assertEqual(
            {"schemaVersion": 1, "action": "capture"},
            session.calls[0],
        )
        self.assertEqual(400, failure.status_code)
        self.assertEqual(
            {
                "schemaVersion": 1,
                "code": "invalid_interactive_action",
                "detail": "interactive action violates the XUI Lab contract",
                "operation": "inspector.action",
                "retryable": False,
            },
            {
                key: failure.json()[key]
                for key in (
                    "schemaVersion",
                    "code",
                    "detail",
                    "operation",
                    "retryable",
                )
            },
        )
        self.assertEqual("application/problem+json", failure.headers["content-type"])
        self.assertNotIn("int_type", json.dumps(failure.json()))

    def test_problem_details_preserve_the_action_request_id(self) -> None:
        with self.client(SessionStub()) as client:
            failure = client.post(
                "/api/v1/actions",
                json={
                    "schemaVersion": 1,
                    "requestId": "req_invalid",
                    "action": "pick",
                    "x": "wrong",
                    "y": 20,
                },
            )
        self.assertEqual(400, failure.status_code)
        self.assertEqual("req_invalid", failure.json()["requestId"])

    def test_rejects_oversized_action_bodies_before_parsing(self) -> None:
        with self.client(SessionStub()) as client:
            response = client.post(
                "/api/v1/actions",
                content=b"{" + b"x" * (MAX_ACTION_BYTES + 1),
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(413, response.status_code)
        self.assertEqual("invalid_input", response.json()["code"])
        self.assertTrue(response.json()["detail"].endswith("bytes"))

    def test_serves_versioned_captures(self) -> None:
        directory = Path(tempfile.mkdtemp())
        png = directory / "latest.png"
        png.write_bytes(b"png bytes")
        session = SessionStub(png)
        with self.client(session) as client:
            found = client.get("/api/v1/captures/1")
            missing = client.get("/api/v1/captures/9")
        self.assertEqual(200, found.status_code)
        self.assertEqual("image/png", found.headers["content-type"])
        self.assertEqual(b"png bytes", found.content)
        self.assertEqual(404, missing.status_code)
        self.assertEqual("not_found", missing.json()["code"])

    def test_events_stream_invalidation_records(self) -> None:
        session = SessionStub()
        worker = InspectorWorker(session)
        subscriber = None
        worker.start()
        try:
            subscriber = worker.subscribe()
            event = subscriber.get(timeout=1)
        finally:
            if subscriber is not None:
                worker.unsubscribe(subscriber)
            worker.close()
        self.assertIsNotNone(event)
        assert event is not None
        payload = format_sse_event(event).decode()
        self.assertIn("event: invalidate", payload)
        data_line = next(
            line for line in payload.splitlines() if line.startswith("data: ")
        )
        body = json.loads(data_line.removeprefix("data: "))
        self.assertEqual(event.event_id, body["eventId"])
        self.assertEqual(event.state_version, body["stateVersion"])

    def test_subscribe_replays_every_event_after_last_event_id(self) -> None:
        session = SessionStub()
        worker = InspectorWorker(session)
        worker.start()
        first_subscriber = worker.subscribe()
        try:
            first = first_subscriber.get(timeout=1)
            assert first is not None
            session.state_value["recording"] = ["one"]
            worker.state()
            session.state_value["recording"] = ["one", "two"]
            worker.state()
            replay = worker.subscribe(last_event_id=first.event_id)
            try:
                replayed = [replay.get(timeout=1), replay.get(timeout=1)]
            finally:
                worker.unsubscribe(replay)
        finally:
            worker.unsubscribe(first_subscriber)
            worker.close()
        self.assertEqual([2, 3], [event.event_id for event in replayed if event])
        self.assertEqual(
            ["invalidate", "invalidate"],
            [event.event_name for event in replayed if event],
        )

    def test_subscribe_requires_refresh_when_last_event_has_expired(self) -> None:
        session = SessionStub()
        worker = InspectorWorker(session, max_replay=2)
        worker.start()
        subscriber = worker.subscribe()
        try:
            first = subscriber.get(timeout=1)
            assert first is not None
            for value in ("one", "two", "three"):
                session.state_value["recording"] = [value]
                worker.state()
            replay = worker.subscribe(last_event_id=first.event_id)
            try:
                reset = replay.get(timeout=1)
            finally:
                worker.unsubscribe(replay)
        finally:
            worker.unsubscribe(subscriber)
            worker.close()
        assert reset is not None
        self.assertEqual("reset", reset.event_name)
        self.assertEqual(4, reset.event_id)

    def test_state_refetch_does_not_publish_an_unchanged_snapshot(self) -> None:
        session = SessionStub()
        worker = InspectorWorker(session)
        worker.start()
        subscriber = worker.subscribe()
        try:
            first = subscriber.get(timeout=1)
            document = worker.state()
            again = worker.state()
            with self.assertRaises(queue.Empty):
                subscriber.get(timeout=0.2)
        finally:
            worker.unsubscribe(subscriber)
            worker.close()
        assert first is not None
        self.assertEqual(1, first.state_version)
        self.assertEqual(1, document["stateVersion"])
        self.assertEqual(1, again["stateVersion"])

    def test_actions_publish_a_new_invalidation(self) -> None:
        session = SessionStub()
        worker = InspectorWorker(session)
        worker.start()
        subscriber = worker.subscribe()
        try:
            first = subscriber.get(timeout=1)
            worker.action({"schemaVersion": 1, "action": "capture"})
            second = subscriber.get(timeout=1)
        finally:
            worker.unsubscribe(subscriber)
            worker.close()
        assert first is not None
        assert second is not None
        self.assertEqual(1, first.state_version)
        self.assertEqual(2, second.state_version)

    def test_watch_publishes_headed_window_changes(self) -> None:
        session = SessionStub()
        worker = InspectorWorker(session)
        with patch("xui_lab.inspector_http.WATCH_INTERVAL_SECONDS", 0.05):
            worker.start()
            subscriber = worker.subscribe()
            try:
                first = subscriber.get(timeout=1)
                session.state_value["recording"] = ["window.click()"]
                second = subscriber.get(timeout=1)
            finally:
                worker.unsubscribe(subscriber)
                worker.close()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None
        assert second is not None
        self.assertEqual(1, first.state_version)
        self.assertEqual(2, second.state_version)

    def test_worker_runs_mutating_actions_in_request_order(self) -> None:
        session = SessionStub()
        session.action_delay = 0.05
        worker = InspectorWorker(session, max_queue=8)
        worker.start()
        try:
            threads = [
                threading.Thread(target=worker.action, args=({"action": name},))
                for name in ("capture", "reload", "export")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
        finally:
            worker.close()
        paired = list(zip(session.order[::2], session.order[1::2], strict=True))
        self.assertEqual(3, len(paired))
        for start, end in paired:
            self.assertEqual("start", start[0])
            self.assertEqual("end", end[0])
            self.assertEqual(start[1], end[1])

    def test_worker_rejects_a_full_queue(self) -> None:
        session = SessionStub()
        session.release.clear()
        worker = InspectorWorker(session, max_queue=1)
        worker.start()
        holder = threading.Thread(target=worker.action, args=({"action": "capture"},))
        queued = threading.Thread(target=worker.action, args=({"action": "reload"},))
        try:
            holder.start()
            self.assertTrue(session.started.wait(timeout=1))
            queued.start()
            time.sleep(0.05)
            with self.assertRaises(InspectorBusyError):
                worker.action({"action": "export"})
        finally:
            session.release.set()
            holder.join(timeout=2)
            queued.join(timeout=2)
            worker.close()

    def test_lifespan_starts_and_stops_the_worker(self) -> None:
        session = SessionStub()
        worker = InspectorWorker(session)
        app = create_inspector_app(worker, session_token=SESSION_TOKEN)
        with TestClient(app) as client:
            client.get("/")
            self.assertEqual(200, client.get("/api/v1/state").status_code)
            thread = worker._thread
            self.assertIsNotNone(thread)
        assert thread is not None
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_state_rejects_oversized_snapshots(self) -> None:
        session = SessionStub()
        with patch("xui_lab.inspector_http.MAX_STATE_BYTES", 32):
            with self.client(session) as client:
                response = client.get("/api/v1/state")
        self.assertEqual(413, response.status_code)
        self.assertEqual("response_too_large", response.json()["code"])

    def test_openapi_document_covers_the_versioned_routes(self) -> None:
        document = inspector_openapi_document()
        paths = document["paths"]
        self.assertIn("/api/v1/state", paths)
        self.assertIn("get", paths["/api/v1/state"])
        self.assertIn("/api/v1/actions", paths)
        self.assertIn("post", paths["/api/v1/actions"])
        self.assertIn("/api/v1/events", paths)
        self.assertIn("/api/v1/captures/{version}", paths)
        self.assertEqual(
            {"$ref": "#/components/schemas/InteractiveAction"},
            paths["/api/v1/actions"]["post"]["requestBody"]["content"][
                "application/json"
            ]["schema"],
        )
        self.assertIn("InteractiveAction", document["components"]["schemas"])
        self.assertIn(
            "stateVersion",
            document["components"]["schemas"]["InspectorStateDocument"]["required"],
        )
        self.assertNotIn("/docs", paths)
        self.assertNotIn("HTTPValidationError", document["components"]["schemas"])

    def test_embedded_client_uses_the_server_openapi_hash(self) -> None:
        source = Path("inspector/src/generated/openapi-hash.ts").read_text(
            encoding="utf-8"
        )
        match = re.fullmatch(r'export const OPENAPI_HASH = "([0-9a-f]{64})";\n', source)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(inspector_openapi_hash(), match.group(1))


if __name__ == "__main__":
    unittest.main()
