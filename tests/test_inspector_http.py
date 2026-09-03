"""HTTP contract tests for the FastAPI inspector."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from xui_lab.errors import InputError
from xui_lab.inspector_http import (
    MAX_ACTION_BYTES,
    SECURITY_HEADERS,
    InspectorBusyError,
    InspectorWorker,
    _RedactTokenFilter,
    contained_session_file,
    create_inspector_app,
    format_sse_event,
    inspector_host_allowed,
    inspector_openapi_document,
    inspector_openapi_hash,
    inspector_origin_allowed,
    inspector_public_url,
)

SESSION_TOKEN = "test-inspector-token"
BASE_URL = "http://127.0.0.1"


class SessionStub:
    def __init__(
        self, capture: Path | None = None, artifact_dir: Path | None = None
    ) -> None:
        self.latest_capture = capture
        self._artifact_dir = artifact_dir or Path("/tmp/xui-lab-inspector")
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
            "artifactDir": str(self._artifact_dir),
            "subjects": ["test_widgets"],
            "fixtures": [],
            "scenarios": ["test_floater"],
            "inputOperations": ["click"],
            "capture": {
                "available": capture is not None,
                "version": 1 if capture is not None else 0,
            },
            "captures": [],
        }

    def artifact_directory(self) -> Path:
        return self._artifact_dir

    def capture_path(self, version: int) -> Path | None:
        if self.latest_capture is None or version != 1:
            return None
        return self.latest_capture

    def capture_snapshot(self, version: int) -> dict[str, Any] | None:
        if self.latest_capture is None or version != 1:
            return None
        return {
            "version": 1,
            "sequence": 1,
            "action": "initial",
            "name": "interactive-0001-initial",
            "tree": self.state_value["tree"],
            "diagnostics": self.state_value["diagnostics"],
            "recording": self.state_value["recording"],
            "locators": self.state_value["locators"],
        }

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
    def client(self, session: SessionStub, *, port: int | None = None) -> TestClient:
        client = TestClient(
            create_inspector_app(
                InspectorWorker(session),
                session_token=SESSION_TOKEN,
                host="127.0.0.1",
                port=port,
            ),
            base_url=BASE_URL if port is None else f"{BASE_URL}:{port}",
        )
        client.cookies.set("xui_lab_session", SESSION_TOKEN)
        return client

    def test_index_issues_session_cookie_and_api_requires_it(self) -> None:
        app = create_inspector_app(
            InspectorWorker(SessionStub()), session_token=SESSION_TOKEN
        )
        with TestClient(app, base_url=BASE_URL) as client:
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
        session = SessionStub(png, artifact_dir=directory)
        with self.client(session) as client:
            found = client.get("/api/v1/captures/1")
            missing = client.get("/api/v1/captures/9")
            ignored_path = client.get(
                "/api/v1/captures/1", params={"path": "/etc/passwd"}
            )
        self.assertEqual(200, found.status_code)
        self.assertEqual("image/png", found.headers["content-type"])
        self.assertEqual(b"png bytes", found.content)
        self.assertEqual(b"png bytes", ignored_path.content)
        self.assertEqual(404, missing.status_code)
        self.assertEqual("not_found", missing.json()["code"])

    def test_serves_a_historical_capture_snapshot(self) -> None:
        directory = Path(tempfile.mkdtemp())
        png = directory / "latest.png"
        png.write_bytes(b"png bytes")
        session = SessionStub(png, artifact_dir=directory)
        with self.client(session) as client:
            found = client.get("/api/v1/captures/1/snapshot")
            missing = client.get("/api/v1/captures/9/snapshot")
        self.assertEqual(200, found.status_code)
        payload = found.json()
        self.assertEqual(1, payload["version"])
        self.assertEqual("initial", payload["action"])
        self.assertEqual("root", payload["tree"]["control_id"])
        self.assertEqual(404, missing.status_code)

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
        with TestClient(app, base_url=BASE_URL) as client:
            client.cookies.set("xui_lab_session", SESSION_TOKEN)
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
        self.assertIn("/api/v1/captures/{version}/snapshot", paths)
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

    def test_built_client_does_not_compile_javascript_at_runtime(self) -> None:
        source = Path("xui_lab/_inspector/assets/app.js").read_text(encoding="utf-8")
        self.assertNotIn("Error compiling schema", source)
        self.assertNotIn("Function(", source)
        self.assertNotIn("unsafe-eval", SECURITY_HEADERS["Content-Security-Policy"])

    def test_rejects_non_loopback_bind_addresses(self) -> None:
        with self.assertRaisesRegex(InputError, "loopback"):
            create_inspector_app(session_token=SESSION_TOKEN, host="0.0.0.0")

    def test_loopback_host_and_origin_rules(self) -> None:
        self.assertTrue(inspector_host_allowed("127.0.0.1", port=None))
        self.assertTrue(inspector_host_allowed("127.0.0.1:8765", port=8765))
        self.assertTrue(inspector_host_allowed("localhost:8765", port=8765))
        self.assertTrue(inspector_host_allowed("[::1]:8765", port=8765))
        self.assertFalse(inspector_host_allowed("evil.example", port=None))
        self.assertFalse(inspector_host_allowed("127.0.0.1.attacker.com", port=None))
        self.assertFalse(inspector_host_allowed("127.0.0.1:9999", port=8765))
        self.assertFalse(inspector_host_allowed(None, port=None))
        self.assertTrue(inspector_origin_allowed(None, port=8765))
        self.assertTrue(inspector_origin_allowed("http://127.0.0.1:8765", port=8765))
        self.assertFalse(inspector_origin_allowed("http://evil.example", port=None))
        self.assertFalse(inspector_origin_allowed("null", port=None))
        self.assertFalse(inspector_origin_allowed("https://127.0.0.1:8765", port=8765))
        self.assertEqual(
            "http://127.0.0.1:8765/", inspector_public_url("127.0.0.1", 8765)
        )
        self.assertEqual("http://[::1]:8765/", inspector_public_url("::1", 8765))

    def test_rejects_unexpected_host_and_origin_headers(self) -> None:
        app = create_inspector_app(
            InspectorWorker(SessionStub()),
            session_token=SESSION_TOKEN,
            port=8765,
        )
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            client.cookies.set("xui_lab_session", SESSION_TOKEN)
            host = client.get("http://evil.example:8765/api/v1/state")
            origin = client.get(
                "/api/v1/state", headers={"Origin": "http://evil.example"}
            )
            allowed = client.get(
                "/api/v1/state", headers={"Origin": "http://127.0.0.1:8765"}
            )
        self.assertEqual(403, host.status_code)
        self.assertEqual("invalid_host", host.json()["code"])
        self.assertEqual("application/problem+json", host.headers["content-type"])
        self.assertEqual(403, origin.status_code)
        self.assertEqual("invalid_origin", origin.json()["code"])
        self.assertEqual(200, allowed.status_code)

    def test_refuses_captures_outside_the_session_artifact_directory(self) -> None:
        directory = Path(tempfile.mkdtemp())
        outside = Path(tempfile.mkdtemp()) / "secret.png"
        outside.write_bytes(b"not a session artifact")
        session = SessionStub(outside, artifact_dir=directory)
        with self.client(session) as client:
            response = client.get("/api/v1/captures/1")
        self.assertEqual(404, response.status_code)
        self.assertEqual("not_found", response.json()["code"])
        self.assertNotIn(str(outside), response.text)

    def test_contained_session_file_rejects_escaped_paths(self) -> None:
        directory = Path(tempfile.mkdtemp())
        inside = directory / "frame.png"
        inside.write_bytes(b"png")
        outside = directory.parent / "outside.png"
        outside.write_bytes(b"no")
        self.assertEqual(inside.resolve(), contained_session_file(inside, directory))
        self.assertIsNone(contained_session_file(outside, directory))
        self.assertIsNone(
            contained_session_file(directory / ".." / outside.name, directory)
        )

    def test_session_token_stays_out_of_payloads_and_logs(self) -> None:
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="cookie %s=%s",
            args=("xui_lab_session", SESSION_TOKEN),
            exc_info=None,
        )
        self.assertTrue(_RedactTokenFilter(SESSION_TOKEN).filter(record))
        self.assertNotIn(SESSION_TOKEN, record.getMessage())
        self.assertIn("[redacted]", record.getMessage())
        with self.client(SessionStub()) as client:
            state = client.get("/api/v1/state")
            action = client.post("/api/v1/actions", json={"action": "capture"})
            denied = client.get("/api/v1/state", headers={"Origin": "http://evil.test"})
        self.assertNotIn(SESSION_TOKEN, state.text)
        self.assertNotIn(SESSION_TOKEN, action.text)
        self.assertNotIn(SESSION_TOKEN, denied.text)

    def test_worker_close_disconnects_sse_subscribers(self) -> None:
        session = SessionStub()
        worker = InspectorWorker(session)
        worker.start()
        subscriber = worker.subscribe()
        try:
            self.assertIsNotNone(subscriber.get(timeout=1))
            worker.close()
            self.assertIsNone(subscriber.get(timeout=1))
            self.assertEqual([], worker._subscribers)
        finally:
            worker.close()

    def test_content_types_match_the_inspector_contract(self) -> None:
        directory = Path(tempfile.mkdtemp())
        png = directory / "latest.png"
        png.write_bytes(b"png bytes")
        with self.client(SessionStub(png, artifact_dir=directory)) as client:
            html = client.get("/")
            state = client.get("/api/v1/state")
            capture = client.get("/api/v1/captures/1")
            problem = client.post("/api/v1/actions", json={"action": "missing"})
        events = inspector_openapi_document()["paths"]["/api/v1/events"]["get"]
        self.assertEqual("text/html; charset=utf-8", html.headers["content-type"])
        self.assertEqual("application/json", state.headers["content-type"])
        self.assertEqual("image/png", capture.headers["content-type"])
        self.assertEqual("application/problem+json", problem.headers["content-type"])
        self.assertIn("text/event-stream", events["responses"]["200"]["content"])
        for name, value in SECURITY_HEADERS.items():
            self.assertEqual(value, state.headers[name.lower()])


class InspectorAsgiTests(unittest.IsolatedAsyncioTestCase):
    async def test_httpx_drives_the_asgi_app_without_a_socket(self) -> None:
        session = SessionStub()
        worker = InspectorWorker(session)
        worker.start()
        app = create_inspector_app(worker, session_token=SESSION_TOKEN)
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url=BASE_URL
            ) as client:
                rejected = await client.get("/api/v1/state")
                index = await client.get("/")
                accepted = await client.get("/api/v1/state")
        finally:
            worker.close()
        self.assertEqual(401, rejected.status_code)
        self.assertEqual("invalid_session", rejected.json()["code"])
        self.assertEqual(200, index.status_code)
        self.assertEqual(200, accepted.status_code)
        self.assertIn("HttpOnly", index.headers["set-cookie"])

    async def test_sse_disconnect_unsubscribes_without_opening_a_port(self) -> None:
        session = SessionStub()
        worker = InspectorWorker(session)
        worker.start()
        app = create_inspector_app(worker, session_token=SESSION_TOKEN)
        incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        await incoming.put({"type": "http.request", "body": b"", "more_body": False})
        disconnected = False

        async def receive() -> dict[str, Any]:
            return await incoming.get()

        async def send(message: dict[str, Any]) -> None:
            nonlocal disconnected
            if message["type"] == "http.response.body" and not disconnected:
                disconnected = True
                await incoming.put({"type": "http.disconnect"})

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/events",
            "raw_path": b"/api/v1/events",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"127.0.0.1"),
                (b"cookie", f"xui_lab_session={SESSION_TOKEN}".encode()),
                (b"accept", b"text/event-stream"),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 80),
        }
        try:
            await asyncio.wait_for(app(scope, receive, send), timeout=2)
            self.assertEqual([], worker._subscribers)
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
