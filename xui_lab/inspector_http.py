"""ASGI inspector for a headed xui-lab session."""

from __future__ import annotations

import asyncio
import json
import queue
import socket
import threading
import webbrowser
from collections.abc import AsyncIterator
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, TypeAdapter
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import contracts
from .contracts import (
    SCHEMA_VERSION,
    ContractModel,
    ErrorRecord,
    InteractiveAction,
    NonEmptyString,
    NonNegativeInt,
    parse_interactive_action,
)
from .errors import InputError, RuntimeFailure, XUILabError
from .inspector_assets import (
    INSPECTOR_ASSETS,
    inspector_assets_problem,
    inspector_build_instruction,
)

MAX_ACTION_BYTES = 1024 * 1024
MAX_ACTION_RESULT_BYTES = 1024 * 1024
MAX_STATE_BYTES = 8 * 1024 * 1024
MAX_CAPTURE_BYTES = 16 * 1024 * 1024
ACTION_QUEUE_SIZE = 32
EVENT_QUEUE_SIZE = 16
STATE_TIMEOUT_SECONDS = 30.0
ACTION_TIMEOUT_SECONDS = 120.0
EVENT_HEARTBEAT_SECONDS = 15.0
QUEUE_FULL_MESSAGE = "inspector session is busy"
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class InspectorBusyError(InputError):
    """The session worker queue rejected another request."""


class InspectorLimitError(InputError):
    """A request or response exceeded an inspector size limit."""


class InspectorSession(Protocol):
    def action(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def capture_path(self, version: int) -> Path | None: ...

    def close(self) -> None: ...

    def state(self) -> dict[str, Any]: ...


class InspectorCaptureInfo(ContractModel):
    available: bool
    version: NonNegativeInt


class InspectorStateDocument(ContractModel):
    tree: dict[str, Any]
    diagnostics: dict[str, Any]
    recording: list[str]
    locators: dict[str, Any]
    artifact_dir: NonEmptyString = Field(alias="artifactDir")
    subjects: list[str]
    fixtures: list[str]
    scenarios: list[str]
    input_operations: list[str] = Field(alias="inputOperations")
    capture: InspectorCaptureInfo


class InspectorActionAccepted(ContractModel):
    ok: Literal[True]
    result: dict[str, Any]


class InspectorActionRejected(ContractModel):
    ok: Literal[False]
    error: ErrorRecord


class InspectorErrorBody(ContractModel):
    error: ErrorRecord


class InspectorSessionEvent(ContractModel):
    event_id: NonNegativeInt = Field(alias="eventId")
    state_version: NonNegativeInt = Field(alias="stateVersion")
    request_id: NonEmptyString | None = Field(default=None, alias="requestId")
    capture_version: NonNegativeInt | None = Field(default=None, alias="captureVersion")


@dataclass(frozen=True)
class _SessionEvent:
    event_id: int
    state_version: int
    request_id: str | None
    capture_version: int | None

    def payload(self) -> dict[str, Any]:
        return InspectorSessionEvent(
            eventId=self.event_id,
            stateVersion=self.state_version,
            requestId=self.request_id,
            captureVersion=self.capture_version,
        ).model_dump(mode="json", by_alias=True, exclude_none=True)


@dataclass
class _Job:
    kind: Literal["state", "action"]
    payload: dict[str, Any] | None = None
    future: Future[Any] = field(default_factory=Future)


def freeze_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def require_object(value: Any, *, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeFailure(f"{what} must be an object")
    return value


def encoded_json(value: Any) -> bytes:
    return json.dumps(value).encode()


def http_error_record(
    message: str,
    *,
    code: str,
    operation: str,
    retryable: bool = False,
) -> ErrorRecord:
    return ErrorRecord(
        schemaVersion=SCHEMA_VERSION,
        type="error",
        code=code,
        message=message,
        operation=operation,
        retryable=retryable,
    )


def operation_for(path: str) -> str:
    if path.rstrip("/").endswith("/actions"):
        return "inspector.action"
    if "/captures/" in path:
        return "inspector.capture"
    if path.rstrip("/").endswith("/state"):
        return "inspector.state"
    if path.rstrip("/").endswith("/events"):
        return "inspector.events"
    return "inspector"


def error_json(
    record: ErrorRecord,
    *,
    status: int,
    action: bool = False,
) -> JSONResponse:
    payload = record.model_dump(mode="json", by_alias=True, exclude_none=True)
    body: dict[str, Any] = {"error": payload}
    if action:
        body = {"ok": False, "error": payload}
    return JSONResponse(body, status_code=status)


class InspectorWorker:
    def __init__(
        self, session: InspectorSession, *, max_queue: int = ACTION_QUEUE_SIZE
    ):
        self._session = session
        self._jobs: queue.Queue[_Job | None] = queue.Queue(maxsize=max_queue)
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._subscribers: list[queue.Queue[_SessionEvent | None]] = []
        self._subscriber_lock = threading.Lock()
        self._snapshot: dict[str, Any] = {}
        self._state_version = 0
        self._event_id = 0
        self._latest_event: _SessionEvent | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="xui-lab-inspector",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._shutdown.set()
        try:
            self._jobs.put_nowait(None)
        except queue.Full:
            pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            if job is not None and not job.future.done():
                job.future.set_exception(RuntimeFailure("inspector is shutting down"))
        with self._subscriber_lock:
            subscribers = list(self._subscribers)
            self._subscribers.clear()
        for subscriber in subscribers:
            self._disconnect(subscriber)

    def state(self, *, timeout: float = STATE_TIMEOUT_SECONDS) -> dict[str, Any]:
        return require_object(
            self._submit(_Job(kind="state"), timeout=timeout),
            what="inspector state",
        )

    def action(
        self,
        request: dict[str, Any],
        *,
        timeout: float = ACTION_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        return require_object(
            self._submit(_Job(kind="action", payload=request), timeout=timeout),
            what="inspector action result",
        )

    def capture_path(self, version: int) -> Path | None:
        return self._session.capture_path(version)

    def subscribe(self) -> queue.Queue[_SessionEvent | None]:
        subscriber: queue.Queue[_SessionEvent | None] = queue.Queue(
            maxsize=EVENT_QUEUE_SIZE
        )
        latest = self._latest_event
        if latest is not None:
            subscriber.put_nowait(latest)
        with self._subscriber_lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[_SessionEvent | None]) -> None:
        with self._subscriber_lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def _submit(self, job: _Job, *, timeout: float) -> Any:
        if self._shutdown.is_set():
            raise RuntimeFailure("inspector is shutting down")
        try:
            self._jobs.put_nowait(job)
        except queue.Full as error:
            raise InspectorBusyError(QUEUE_FULL_MESSAGE) from error
        try:
            return job.future.result(timeout=timeout)
        except FutureTimeout as error:
            raise RuntimeFailure("inspector request timed out") from error

    def _run(self) -> None:
        try:
            self._publish_state(request_id=None)
        except Exception:
            pass
        while not self._shutdown.is_set():
            try:
                job = self._jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            if job is None:
                break
            self._complete(job)

    def _complete(self, job: _Job) -> None:
        try:
            if job.kind == "action":
                if job.payload is None:
                    raise InputError("request must be an object")
                result = freeze_json(self._session.action(job.payload))
                self._publish_state(request_id=_request_id(job.payload))
                encoded = encoded_json({"ok": True, "result": result})
                if len(encoded) > MAX_ACTION_RESULT_BYTES:
                    raise InspectorLimitError(
                        "action result exceeds the inspector inline limit"
                    )
                job.future.set_result(result)
                return
            snapshot = self._publish_state(request_id=None)
            job.future.set_result(snapshot)
        except Exception as error:
            if not job.future.done():
                job.future.set_exception(error)

    def _publish_state(self, *, request_id: str | None) -> dict[str, Any]:
        snapshot = require_object(
            freeze_json(self._session.state()), what="inspector state"
        )
        self._snapshot = snapshot
        self._state_version += 1
        capture = snapshot.get("capture")
        capture_version = None
        if isinstance(capture, dict):
            version = capture.get("version")
            if isinstance(version, int):
                capture_version = version
        self._event_id += 1
        event = _SessionEvent(
            event_id=self._event_id,
            state_version=self._state_version,
            request_id=request_id,
            capture_version=capture_version,
        )
        self._latest_event = event
        with self._subscriber_lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                self._disconnect(subscriber)
                with self._subscriber_lock:
                    if subscriber in self._subscribers:
                        self._subscribers.remove(subscriber)
        return snapshot

    def _disconnect(self, subscriber: queue.Queue[_SessionEvent | None]) -> None:
        try:
            subscriber.put_nowait(None)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(None)
            except queue.Full:
                pass


def format_sse_event(event: _SessionEvent) -> bytes:
    payload = json.dumps(event.payload(), separators=(",", ":"))
    return (f"id: {event.event_id}\nevent: invalidate\ndata: {payload}\n\n").encode()


def _request_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("requestId")
    return value if isinstance(value, str) and value else None


class _SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.decode().lower() for key, _value in headers}
                for name, value in SECURITY_HEADERS.items():
                    if name.lower() not in existing:
                        headers.append((name.lower().encode(), value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_inspector_app(worker: InspectorWorker | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configured = getattr(app.state, "worker", None)
        if isinstance(configured, InspectorWorker):
            configured.start()
        try:
            yield
        finally:
            if isinstance(configured, InspectorWorker):
                configured.close()

    app = FastAPI(
        title="XUI Lab Inspector",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    if worker is not None:
        app.state.worker = worker
    app.add_middleware(_SecurityHeadersMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        operation = operation_for(request.url.path)
        record = http_error_record(
            str(exc.detail) or "not found",
            code="not_found" if exc.status_code == 404 else "http_error",
            operation=operation,
        )
        return error_json(
            record,
            status=exc.status_code,
            action=operation == "inspector.action",
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        operation = operation_for(request.url.path)
        record = contracts.contract_error(
            "interactive action" if operation == "inspector.action" else operation,
            operation=operation,
        )
        return error_json(record, status=400, action=operation == "inspector.action")

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(
            INSPECTOR_ASSETS / "index.html", media_type="text/html; charset=utf-8"
        )

    @app.get(
        "/api/v1/state",
        response_model=InspectorStateDocument,
        responses={413: {"model": InspectorErrorBody}},
    )
    def get_state(request: Request) -> Response:
        current = _worker(request)
        try:
            snapshot = current.state()
        except InspectorBusyError as error:
            record = http_error_record(
                str(error),
                code="queue_full",
                operation="inspector.state",
                retryable=True,
            )
            return error_json(record, status=429)
        except InspectorLimitError as error:
            return error_json(
                http_error_record(
                    str(error),
                    code="response_too_large",
                    operation="inspector.state",
                ),
                status=413,
            )
        except XUILabError as error:
            return error_json(
                contracts.error_record(error, operation="inspector.state"),
                status=400,
            )
        encoded = encoded_json(snapshot)
        if len(encoded) > MAX_STATE_BYTES:
            return error_json(
                http_error_record(
                    "inspector state exceeds the inline response limit",
                    code="response_too_large",
                    operation="inspector.state",
                ),
                status=413,
            )
        return Response(encoded, media_type="application/json")

    @app.post(
        "/api/v1/actions",
        response_model=InspectorActionAccepted,
        responses={
            400: {"model": InspectorActionRejected},
            413: {"model": InspectorActionRejected},
            429: {"model": InspectorActionRejected},
        },
    )
    async def post_actions(request: Request) -> Response:
        current = _worker(request)
        body, error = await _read_action_body(request)
        if error is not None:
            return error
        try:
            value = json.loads(body)
        except ValueError:
            return error_json(
                http_error_record(
                    "request must be JSON",
                    code="invalid_input",
                    operation="inspector.action",
                ),
                status=400,
                action=True,
            )
        if not isinstance(value, dict):
            return error_json(
                http_error_record(
                    "request must be an object",
                    code="invalid_input",
                    operation="inspector.action",
                ),
                status=400,
                action=True,
            )
        if "schemaVersion" not in value:
            value = {"schemaVersion": 1, **value}
        try:
            parse_interactive_action(value)
            result = current.action(value)
        except InspectorBusyError as error:
            return error_json(
                http_error_record(
                    str(error),
                    code="queue_full",
                    operation="inspector.action",
                    retryable=True,
                ),
                status=429,
                action=True,
            )
        except InspectorLimitError as error:
            return error_json(
                http_error_record(
                    str(error),
                    code="response_too_large",
                    operation="inspector.action",
                ),
                status=413,
                action=True,
            )
        except XUILabError as error:
            return error_json(
                contracts.error_record(error, operation="inspector.action"),
                status=400,
                action=True,
            )
        return JSONResponse({"ok": True, "result": result})

    @app.get(
        "/api/v1/events",
        responses={
            200: {
                "content": {
                    "text/event-stream": {
                        "schema": TypeAdapter(InspectorSessionEvent).json_schema()
                    }
                }
            }
        },
    )
    async def get_events(request: Request) -> StreamingResponse:
        current = _worker(request)
        subscriber = current.subscribe()

        async def publish() -> AsyncIterator[bytes]:
            last_heartbeat = asyncio.get_running_loop().time()
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = subscriber.get_nowait()
                    except queue.Empty:
                        now = asyncio.get_running_loop().time()
                        if now - last_heartbeat >= EVENT_HEARTBEAT_SECONDS:
                            yield b": ping\n\n"
                            last_heartbeat = now
                        await asyncio.sleep(0.05)
                        continue
                    if event is None:
                        break
                    yield format_sse_event(event)
                    last_heartbeat = asyncio.get_running_loop().time()
            finally:
                current.unsubscribe(subscriber)

        return StreamingResponse(
            publish(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get(
        "/api/v1/captures/{version}",
        responses={
            200: {"content": {"image/png": {}}},
            404: {"model": InspectorErrorBody},
            413: {"model": InspectorErrorBody},
        },
    )
    def get_capture(version: int, request: Request) -> Response:
        if version < 1:
            return error_json(
                http_error_record(
                    "capture version must be a positive integer",
                    code="invalid_input",
                    operation="inspector.capture",
                ),
                status=400,
            )
        current = _worker(request)
        path = current.capture_path(version)
        if path is None:
            return error_json(
                http_error_record(
                    "no screenshot has been captured",
                    code="not_found",
                    operation="inspector.capture",
                ),
                status=404,
            )
        try:
            body = path.read_bytes()
        except OSError:
            return error_json(
                http_error_record(
                    "the requested screenshot is unavailable",
                    code="not_found",
                    operation="inspector.capture",
                ),
                status=404,
            )
        if len(body) > MAX_CAPTURE_BYTES:
            return error_json(
                http_error_record(
                    "capture exceeds the inspector inline limit",
                    code="response_too_large",
                    operation="inspector.capture",
                ),
                status=413,
            )
        return Response(body, media_type="image/png")

    assets = INSPECTOR_ASSETS / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    return app


def _worker(request: Request) -> InspectorWorker:
    worker = getattr(request.app.state, "worker", None)
    if not isinstance(worker, InspectorWorker):
        raise RuntimeFailure("inspector worker is not configured")
    return worker


async def _read_action_body(request: Request) -> tuple[bytes, JSONResponse | None]:
    length_header = request.headers.get("content-length")
    if length_header is not None:
        try:
            length = int(length_header)
        except ValueError:
            return b"", error_json(
                http_error_record(
                    "content-length must be an integer",
                    code="invalid_input",
                    operation="inspector.action",
                ),
                status=400,
                action=True,
            )
        if length < 1 or length > MAX_ACTION_BYTES:
            return b"", error_json(
                http_error_record(
                    f"request body must be between 1 and {MAX_ACTION_BYTES} bytes",
                    code="invalid_input",
                    operation="inspector.action",
                ),
                status=413 if length > MAX_ACTION_BYTES else 400,
                action=True,
            )
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_ACTION_BYTES:
            return b"", error_json(
                http_error_record(
                    f"request body must be between 1 and {MAX_ACTION_BYTES} bytes",
                    code="invalid_input",
                    operation="inspector.action",
                ),
                status=413,
                action=True,
            )
        chunks.append(chunk)
    body = b"".join(chunks)
    if not body:
        return b"", error_json(
            http_error_record(
                f"request body must be between 1 and {MAX_ACTION_BYTES} bytes",
                code="invalid_input",
                operation="inspector.action",
            ),
            status=400,
            action=True,
        )
    return body, None


def inspector_openapi_document() -> dict[str, Any]:
    app = create_inspector_app()
    document = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    action_schema = TypeAdapter(InteractiveAction).json_schema(
        ref_template="#/components/schemas/{model}"
    )
    components = document.setdefault("components", {}).setdefault("schemas", {})
    definitions = action_schema.pop("$defs", {})
    components.update(definitions)
    components["InteractiveAction"] = action_schema
    post = document["paths"]["/api/v1/actions"]["post"]
    post["requestBody"] = {
        "required": True,
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/InteractiveAction"}
            }
        },
    }
    return document


def serve_inspector(
    session: InspectorSession,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
) -> int:
    assets_problem = inspector_assets_problem()
    if assets_problem is not None:
        raise RuntimeFailure(f"{assets_problem}; {inspector_build_instruction()}")
    worker = InspectorWorker(session)
    app = create_inspector_app(worker)
    sock = socket.create_server((host, port))
    bound_host, bound_port = sock.getsockname()[:2]
    url = f"http://{bound_host}:{bound_port}/"
    print(f"xui-lab inspector: {url}", flush=True)
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    config = uvicorn.Config(
        app,
        host=bound_host,
        port=bound_port,
        access_log=False,
        log_config=None,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        return 0
    finally:
        sock.close()
        session.close()
    return 0
