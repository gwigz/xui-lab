"""ASGI inspector for a headed xui-lab session."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import queue
import secrets
import socket
import threading
import webbrowser
from collections import deque
from collections.abc import AsyncIterator
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

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
    PositiveInt,
    Selector,
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
EVENT_REPLAY_SIZE = 16
STATE_TIMEOUT_SECONDS = 30.0
ACTION_TIMEOUT_SECONDS = 120.0
EVENT_HEARTBEAT_SECONDS = 15.0
EVENT_POLL_SECONDS = 0.25
WATCH_INTERVAL_SECONDS = 0.7
QUEUE_FULL_MESSAGE = "inspector session is busy"
SESSION_COOKIE = "xui_lab_session"
LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    # script-src must not include 'unsafe-eval'. The inspector precompiles JSON
    # Schema validators; ajv.compile() at runtime is a hard load failure.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
TOKEN_PLACEHOLDER = "[redacted]"


class InspectorBusyError(InputError):
    """The session worker queue rejected another request."""


class InspectorLimitError(InputError):
    """A request or response exceeded an inspector size limit."""


class InspectorSession(Protocol):
    def action(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def artifact_directory(self) -> Path: ...

    def capture_path(self, version: int) -> Path | None: ...

    def capture_snapshot(self, version: int) -> dict[str, Any] | None: ...

    def close(self) -> None: ...

    def state(self) -> dict[str, Any]: ...


def is_loopback_hostname(hostname: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host in LOOPBACK_HOSTNAMES


def parse_host_header(value: str) -> tuple[str, int | None]:
    host = value.strip()
    if not host:
        raise ValueError("host is empty")
    if host.startswith("["):
        end = host.find("]")
        if end < 0:
            raise ValueError("host IPv6 bracket is unclosed")
        hostname = host[1:end]
        rest = host[end + 1 :]
        if rest == "":
            return hostname, None
        if not rest.startswith(":"):
            raise ValueError("host IPv6 port is invalid")
        return hostname, int(rest[1:])
    if host.count(":") == 1:
        hostname, port_text = host.rsplit(":", 1)
        if not hostname:
            raise ValueError("host is empty")
        return hostname, int(port_text)
    return host, None


def inspector_host_allowed(host_header: str | None, *, port: int | None) -> bool:
    if host_header is None:
        return False
    try:
        hostname, header_port = parse_host_header(host_header)
    except ValueError:
        return False
    if not is_loopback_hostname(hostname):
        return False
    if port is None:
        return True
    actual_port = 80 if header_port is None else header_port
    return actual_port == port


def inspector_origin_allowed(origin: str | None, *, port: int | None) -> bool:
    if origin is None or origin == "":
        return True
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
        or not is_loopback_hostname(parsed.hostname)
    ):
        return False
    if port is None:
        return True
    actual_port = 80 if parsed.port is None else parsed.port
    return actual_port == port


def inspector_public_url(host: str, port: int) -> str:
    hostname = f"[{host}]" if ":" in host else host
    return f"http://{hostname}:{port}/"


def contained_session_file(path: Path, artifact_dir: Path) -> Path | None:
    try:
        resolved = path.resolve()
        root = artifact_dir.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return resolved


class _RedactTokenFilter(logging.Filter):
    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if self._token and self._token in message:
            record.msg = message.replace(self._token, TOKEN_PLACEHOLDER)
            record.args = ()
        return True


def install_token_redaction(token: str) -> None:
    token_filter = _RedactTokenFilter(token)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(
            isinstance(existing, _RedactTokenFilter) for existing in logger.filters
        ):
            logger.addFilter(token_filter)


class InspectorCaptureInfo(ContractModel):
    available: bool
    version: NonNegativeInt


class InspectorFilmstripEntry(ContractModel):
    version: PositiveInt
    sequence: NonNegativeInt
    action: NonEmptyString | None = None
    selector: Selector | None = None
    name: NonEmptyString


class InspectorCaptureSnapshot(ContractModel):
    version: PositiveInt
    sequence: NonNegativeInt
    action: NonEmptyString | None = None
    selector: Selector | None = None
    name: NonEmptyString
    tree: dict[str, Any]
    diagnostics: dict[str, Any]
    recording: list[str]
    locators: dict[str, Any]


class InspectorStateDocument(ContractModel):
    tree: dict[str, Any]
    diagnostics: dict[str, Any]
    recording: list[str]
    locators: dict[str, Any]
    artifact_dir: NonEmptyString = Field(alias="artifactDir")
    subject: NonEmptyString
    fixture: str
    subjects: list[str]
    fixtures: list[str]
    scenarios: list[str]
    input_operations: list[str] = Field(alias="inputOperations")
    capture: InspectorCaptureInfo
    captures: list[InspectorFilmstripEntry] = Field(default_factory=list)
    state_version: NonNegativeInt = Field(alias="stateVersion")
    openapi_hash: NonEmptyString = Field(alias="openapiHash")


class InspectorActionAccepted(ContractModel):
    ok: Literal[True]
    result: dict[str, Any]


class InspectorProblemDetails(ContractModel):
    type: NonEmptyString
    title: NonEmptyString
    status: NonNegativeInt
    detail: NonEmptyString
    schema_version: int = Field(alias="schemaVersion")
    code: NonEmptyString
    operation: NonEmptyString
    retryable: bool
    details: tuple[NonEmptyString, ...] | None = None
    request_id: NonEmptyString | None = Field(default=None, alias="requestId")
    selector: contracts.Selector | None = None
    capability: NonEmptyString | None = None
    artifacts: tuple[NonEmptyString, ...] | None = None
    tree_excerpt: dict[str, Any] | None = Field(default=None, alias="treeExcerpt")


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
    event_name: Literal["invalidate", "reset"] = "invalidate"

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
) -> JSONResponse:
    body = InspectorProblemDetails(
        type=f"https://xui-lab.local/problems/{record.code}",
        title=HTTPStatus(status).phrase,
        status=status,
        detail=record.message,
        schemaVersion=record.schema_version,
        code=record.code,
        operation=record.operation,
        retryable=record.retryable,
        details=record.details,
        requestId=record.request_id,
        selector=record.selector,
        capability=record.capability,
        artifacts=record.artifacts,
        treeExcerpt=record.tree_excerpt,
    ).model_dump(mode="json", by_alias=True, exclude_none=True)
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


class InspectorWorker:
    def __init__(
        self,
        session: InspectorSession,
        *,
        max_queue: int = ACTION_QUEUE_SIZE,
        max_replay: int = EVENT_REPLAY_SIZE,
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
        self._events: deque[_SessionEvent] = deque(maxlen=max_replay)

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
        path = self._session.capture_path(version)
        if path is None:
            return None
        return contained_session_file(path, self._session.artifact_directory())

    def capture_snapshot(self, version: int) -> dict[str, Any] | None:
        getter = getattr(self._session, "capture_snapshot", None)
        if not callable(getter):
            return None
        snapshot = getter(version)
        return snapshot if isinstance(snapshot, dict) else None

    def subscribe(
        self, *, last_event_id: int | None = None
    ) -> queue.Queue[_SessionEvent | None]:
        subscriber: queue.Queue[_SessionEvent | None] = queue.Queue(
            maxsize=EVENT_QUEUE_SIZE
        )
        with self._subscriber_lock:
            events = list(self._events)
            if last_event_id is None:
                if events:
                    subscriber.put_nowait(events[-1])
            elif events and (
                last_event_id < events[0].event_id - 1
                or last_event_id > events[-1].event_id
            ):
                latest = events[-1]
                subscriber.put_nowait(
                    _SessionEvent(
                        event_id=latest.event_id,
                        state_version=latest.state_version,
                        request_id=latest.request_id,
                        capture_version=latest.capture_version,
                        event_name="reset",
                    )
                )
            else:
                for event in events:
                    if event.event_id > last_event_id:
                        subscriber.put_nowait(event)
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
                job = self._jobs.get(timeout=WATCH_INTERVAL_SECONDS)
            except queue.Empty:
                self._watch()
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
            job.future.set_result(self._state_document(snapshot))
        except Exception as error:
            if not job.future.done():
                job.future.set_exception(error)

    def _watch(self) -> None:
        if self._shutdown.is_set():
            return
        try:
            self._publish_state(request_id=None)
        except Exception:
            pass

    def _state_document(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            **snapshot,
            "stateVersion": self._state_version,
            "openapiHash": inspector_openapi_hash(),
        }

    def _publish_state(self, *, request_id: str | None) -> dict[str, Any]:
        snapshot = require_object(
            freeze_json(self._session.state()), what="inspector state"
        )
        if snapshot == self._snapshot and self._latest_event is not None:
            return snapshot
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
            self._events.append(event)
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
    return (
        f"id: {event.event_id}\nevent: {event.event_name}\ndata: {payload}\n\n"
    ).encode()


def _request_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("requestId")
    return value if isinstance(value, str) and value else None


class _InspectorGateMiddleware:
    def __init__(self, app: ASGIApp, *, session_token: str, port: int | None) -> None:
        self.app = app
        self._session_token = session_token
        self._port = port

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

        request = Request(scope)
        operation = operation_for(request.url.path)
        if not inspector_host_allowed(request.headers.get("host"), port=self._port):
            record = http_error_record(
                "inspector host is not allowed",
                code="invalid_host",
                operation=operation,
            )
            await error_json(record, status=403)(scope, receive, send_with_headers)
            return
        if not inspector_origin_allowed(request.headers.get("origin"), port=self._port):
            record = http_error_record(
                "inspector origin is not allowed",
                code="invalid_origin",
                operation=operation,
            )
            await error_json(record, status=403)(scope, receive, send_with_headers)
            return
        if request.url.path.startswith("/api/v1/") and not secrets.compare_digest(
            request.cookies.get(SESSION_COOKIE, ""), self._session_token
        ):
            record = http_error_record(
                "inspector session is invalid",
                code="invalid_session",
                operation=operation,
            )
            await error_json(record, status=401)(scope, receive, send_with_headers)
            return

        await self.app(scope, receive, send_with_headers)


def create_inspector_app(
    worker: InspectorWorker | None = None,
    *,
    session_token: str,
    host: str = "127.0.0.1",
    port: int | None = None,
) -> FastAPI:
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

    if not is_loopback_hostname(host):
        raise InputError("inspector must bind to a loopback address")
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
    app.add_middleware(_InspectorGateMiddleware, session_token=session_token, port=port)

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
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        operation = operation_for(request.url.path)
        record = contracts.contract_error(
            "interactive action" if operation == "inspector.action" else operation,
            operation=operation,
            details=contracts.request_details(exc.errors()),
        )
        return error_json(record, status=400)

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def index() -> FileResponse:
        response = FileResponse(
            INSPECTOR_ASSETS / "index.html", media_type="text/html; charset=utf-8"
        )
        response.set_cookie(
            SESSION_COOKIE,
            session_token,
            httponly=True,
            samesite="strict",
            path="/api/v1",
        )
        return response

    @app.get(
        "/api/v1/state",
        response_model=InspectorStateDocument,
        responses={413: {"model": InspectorProblemDetails}},
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
            400: {"model": InspectorProblemDetails},
            413: {"model": InspectorProblemDetails},
            429: {"model": InspectorProblemDetails},
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
            )
        if not isinstance(value, dict):
            return error_json(
                http_error_record(
                    "request must be an object",
                    code="invalid_input",
                    operation="inspector.action",
                ),
                status=400,
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
            )
        except InspectorLimitError as error:
            return error_json(
                http_error_record(
                    str(error),
                    code="response_too_large",
                    operation="inspector.action",
                ),
                status=413,
            )
        except XUILabError as error:
            return error_json(
                contracts.error_record(
                    error,
                    operation="inspector.action",
                    request_id=_request_id(value),
                ),
                status=400,
            )
        return JSONResponse({"ok": True, "result": result})

    @app.get(
        "/api/v1/events",
        responses={
            400: {"model": InspectorProblemDetails},
            200: {
                "content": {
                    "text/event-stream": {
                        "schema": TypeAdapter(InspectorSessionEvent).json_schema()
                    }
                }
            },
        },
    )
    async def get_events(request: Request) -> Response:
        current = _worker(request)
        last_event_id, error = _last_event_id(request)
        if error is not None:
            return error
        subscriber = current.subscribe(last_event_id=last_event_id)

        async def publish() -> AsyncIterator[bytes]:
            last_heartbeat = asyncio.get_running_loop().time()
            try:
                yield b": connected\n\n"
                while True:
                    try:
                        event = await asyncio.to_thread(
                            subscriber.get, True, EVENT_POLL_SECONDS
                        )
                    except queue.Empty:
                        if await request.is_disconnected():
                            break
                        now = asyncio.get_running_loop().time()
                        if now - last_heartbeat >= EVENT_HEARTBEAT_SECONDS:
                            yield b": ping\n\n"
                            last_heartbeat = now
                        continue
                    if event is None:
                        break
                    yield format_sse_event(event)
                    last_heartbeat = asyncio.get_running_loop().time()
                    if await request.is_disconnected():
                        break
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
            400: {"model": InspectorProblemDetails},
            404: {"model": InspectorProblemDetails},
            413: {"model": InspectorProblemDetails},
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

    @app.get(
        "/api/v1/captures/{version}/snapshot",
        response_model=InspectorCaptureSnapshot,
        responses={
            400: {"model": InspectorProblemDetails},
            404: {"model": InspectorProblemDetails},
        },
    )
    def get_capture_snapshot(version: int, request: Request) -> Response:
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
        snapshot = current.capture_snapshot(version)
        if snapshot is None:
            return error_json(
                http_error_record(
                    "no snapshot has been stored for that capture",
                    code="not_found",
                    operation="inspector.capture",
                ),
                status=404,
            )
        try:
            document = InspectorCaptureSnapshot.model_validate(snapshot)
        except ValueError:
            return error_json(
                http_error_record(
                    "stored capture snapshot is invalid",
                    code="not_found",
                    operation="inspector.capture",
                ),
                status=404,
            )
        return Response(
            encoded_json(
                document.model_dump(mode="json", by_alias=True, exclude_none=True)
            ),
            media_type="application/json",
        )

    assets = INSPECTOR_ASSETS / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    return app


def _worker(request: Request) -> InspectorWorker:
    worker = getattr(request.app.state, "worker", None)
    if not isinstance(worker, InspectorWorker):
        raise RuntimeFailure("inspector worker is not configured")
    return worker


def _last_event_id(request: Request) -> tuple[int | None, JSONResponse | None]:
    raw = request.headers.get("last-event-id")
    if raw is None:
        return None, None
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        return None, error_json(
            http_error_record(
                "Last-Event-ID must be a non-negative integer",
                code="invalid_input",
                operation="inspector.events",
            ),
            status=400,
        )
    return value, None


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
            )
        if length < 1 or length > MAX_ACTION_BYTES:
            return b"", error_json(
                http_error_record(
                    f"request body must be between 1 and {MAX_ACTION_BYTES} bytes",
                    code="invalid_input",
                    operation="inspector.action",
                ),
                status=413 if length > MAX_ACTION_BYTES else 400,
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
        )
    return body, None


def inspector_openapi_document() -> dict[str, Any]:
    app = create_inspector_app(session_token="openapi-generation-token")
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
    for path in document["paths"].values():
        for operation in path.values():
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses")
            if not isinstance(responses, dict):
                continue
            responses.pop("422", None)
            responses.setdefault(
                "401",
                {
                    "description": "Unauthorized",
                    "content": {
                        "application/problem+json": {
                            "schema": {
                                "$ref": "#/components/schemas/InspectorProblemDetails"
                            }
                        }
                    },
                },
            )
            for status, response in responses.items():
                if str(status).startswith("2") or not isinstance(response, dict):
                    continue
                content = response.get("content")
                if not isinstance(content, dict):
                    continue
                schema = content.pop("application/json", None)
                if schema is not None:
                    content["application/problem+json"] = schema
    components.pop("HTTPValidationError", None)
    components.pop("ValidationError", None)
    return document


@lru_cache(maxsize=1)
def inspector_openapi_hash() -> str:
    encoded = (
        json.dumps(inspector_openapi_document(), indent=2, sort_keys=True) + "\n"
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def serve_inspector(
    session: InspectorSession,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
) -> int:
    if not is_loopback_hostname(host):
        raise InputError("inspector must bind to a loopback address")
    assets_problem = inspector_assets_problem()
    if assets_problem is not None:
        raise RuntimeFailure(f"{assets_problem}; {inspector_build_instruction()}")
    worker = InspectorWorker(session)
    session_token = secrets.token_urlsafe(32)
    install_token_redaction(session_token)
    sock = socket.create_server((host, port))
    bound_host, bound_port = sock.getsockname()[:2]
    app = create_inspector_app(
        worker,
        session_token=session_token,
        host=bound_host,
        port=bound_port,
    )
    url = inspector_public_url(bound_host, bound_port)
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
