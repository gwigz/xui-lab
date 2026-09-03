"""CLI handlers for persistent sessions."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .api import Lab
from .contracts import (
    SCHEMA_VERSION,
    SessionCloseCliCommand,
    SessionJsonlCliCommand,
    SessionServeCliCommand,
    SessionStartCliCommand,
    SessionStatusCliCommand,
    parse_cli_command,
)
from .domain import Capability, ForkId, Viewport
from .errors import InputError
from .io import resolved_source
from .oneshot import apply_window_command
from .session import (
    SessionFile,
    cleanup_stale,
    list_sessions,
    pid_alive,
    read_session,
    remove_session,
    send_session_command,
    serve_until_closed,
    socket_path,
    terminate_pid,
    wait_until_ready,
    write_session,
)

ROOT = Path(__file__).resolve().parents[1]


def _timeout(command: Any, default: float) -> float:
    return float(command.timeout) if command.timeout is not None else default


def public_session(record: SessionFile, request_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "requestId": request_id,
        "sessionId": record.session_id,
        "status": record.status,
        "pid": record.pid,
        "viewerPid": record.viewer_pid,
        "fork": record.fork,
        "forkCommit": record.fork_commit,
        "subject": record.subject,
        "viewport": {
            "width": record.width,
            "height": record.height,
            "uiScale": record.ui_scale,
        },
        "capabilities": list(record.capabilities),
        "socketPath": record.socket_path,
    }


def emit_document(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def cmd_session_start(
    command: SessionStartCliCommand,
    *,
    select_fork: Callable[[Any], tuple[Any, Path]],
    runtime_path: Callable[..., Path],
    adapter_config: Callable[[Any], Any],
) -> int:
    fork, source = select_fork(command)
    executable = runtime_path(fork, source, command.runtime)
    if not executable.is_file():
        raise InputError(f"runtime executable not found: {executable}")
    adapter = adapter_config(fork)
    if command.subject not in adapter.subjects:
        raise InputError(f"subject is not declared by the adapter: {command.subject}")
    session_id = "sess_" + uuid.uuid4().hex[:16]
    timeout = _timeout(command, 30.0)
    record = SessionFile(
        schemaVersion=SCHEMA_VERSION,
        sessionId=session_id,
        token=secrets.token_urlsafe(32),
        status="starting",
        socketPath=str(socket_path(session_id)),
        subject=command.subject,
        runtime=str(executable),
        source=str(source),
        fork=str(fork.id),
        artifacts=str(Path(command.artifacts).expanduser().resolve()),
        requestId=command.request_id,
        width=command.width,
        height=command.height,
        uiScale=command.ui_scale,
        capabilities=tuple(adapter.subjects[command.subject]),
        viewerSource=command.viewer_source,
        fixture=str(Path(command.fixture).expanduser().resolve())
        if command.fixture
        else None,
    )
    write_session(record)
    argv = [
        sys.executable,
        str(ROOT / "xui-lab"),
        "--request-id",
        command.request_id,
        "session",
        "serve",
        "--session-id",
        session_id,
    ]
    if command.timeout is not None:
        argv.extend(["--timeout", str(command.timeout)])
    process = subprocess.Popen(
        argv,
        cwd=str(ROOT),
        start_new_session=True,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    write_session(record.model_copy(update={"pid": process.pid}))
    try:
        ready = wait_until_ready(session_id, timeout)
    except BaseException:
        terminate_pid(process.pid)
        remove_session(session_id)
        raise
    emit_document(public_session(ready, command.request_id))
    return 0


def cmd_session_status(command: SessionStatusCliCommand) -> int:
    cleanup_stale()
    if command.session_id is not None:
        record = read_session(command.session_id)
        emit_document(public_session(record, command.request_id))
        return 0
    emit_document(
        {
            "schemaVersion": SCHEMA_VERSION,
            "requestId": command.request_id,
            "sessions": [
                public_session(record, command.request_id) for record in list_sessions()
            ],
        }
    )
    return 0


def cmd_session_close(command: SessionCloseCliCommand) -> int:
    cleanup_stale()
    terminated = False
    try:
        record = read_session(command.session_id)
    except InputError:
        emit_document(
            {
                "schemaVersion": SCHEMA_VERSION,
                "requestId": command.request_id,
                "sessionId": command.session_id,
                "closed": True,
                "terminated": False,
            }
        )
        return 0
    timeout = _timeout(command, 10.0)
    if record.status == "ready" and pid_alive(record.pid):
        try:
            send_session_command(
                command.session_id,
                command.model_dump(mode="json", by_alias=True),
                timeout=timeout,
            )
            terminated = True
        except Exception:
            terminated = terminate_pid(record.pid)
    else:
        terminated = terminate_pid(record.pid)
    remove_session(command.session_id)
    emit_document(
        {
            "schemaVersion": SCHEMA_VERSION,
            "requestId": command.request_id,
            "sessionId": command.session_id,
            "closed": True,
            "terminated": terminated,
        }
    )
    return 0


def cmd_session_jsonl(command: SessionJsonlCliCommand) -> int:
    timeout = _timeout(command, 10.0)
    exit_status = 0
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            emit_document(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "type": "error",
                    "code": "invalid_input",
                    "message": "JSONL line is not JSON",
                    "operation": "session",
                    "retryable": False,
                    "requestId": command.request_id,
                }
            )
            exit_status = 2
            continue
        if not isinstance(payload, dict):
            raise InputError("JSONL command must be an object")
        payload.setdefault("schemaVersion", SCHEMA_VERSION)
        payload.setdefault("requestId", command.request_id)
        payload.setdefault("fork", command.fork)
        payload.setdefault("viewerSource", list(command.viewer_source))
        payload.setdefault("session", command.session_id)
        payload.setdefault("timeout", command.timeout)
        inner = parse_cli_command(payload)
        response = send_session_command(
            command.session_id,
            inner.model_dump(mode="json", by_alias=True),
            timeout=timeout,
        )
        emit_document(response)
        if response.get("type") == "error":
            exit_status = 2 if response.get("code") == "invalid_input" else 1
    return exit_status


def cmd_session_serve(command: SessionServeCliCommand) -> int:
    record = read_session(command.session_id)
    from .cli import load_manifest

    manifest = load_manifest()
    fork = manifest.forks[ForkId(record.fork)]
    source = Path(record.source)
    resolved_source(fork, {ForkId(record.fork): source})
    timeout = _timeout(command, 10.0)
    lab = Lab(
        ROOT,
        fork,
        source,
        Path(record.runtime),
        Path(record.artifacts),
    )
    fixture = Path(record.fixture) if record.fixture else None
    try:
        with lab.open(
            artifact_id=record.session_id,
            subject=record.subject,
            viewport=Viewport(record.width, record.height, record.ui_scale),
            capabilities=frozenset(Capability(value) for value in record.capabilities),
            fixture=fixture,
            request_id=record.request_id,
            request_timeout=timeout,
            shutdown_timeout=timeout,
        ) as window:

            def on_ready(pid: int) -> None:
                write_session(
                    record.model_copy(
                        update={
                            "status": "ready",
                            "pid": pid,
                            "viewer_pid": window.runtime.pid,
                            "fork_commit": window._fork_commit,
                        }
                    )
                )

            def handler(inner: Any) -> dict[str, Any]:
                return apply_window_command(window, inner)

            serve_until_closed(record, handler, on_ready=on_ready)
    except Exception as error:
        write_session(
            record.model_copy(update={"status": "closed", "error": str(error)})
        )
        raise
    remove_session(command.session_id)
    return 0


def cmd_session_bound(command: Any) -> int:
    timeout = _timeout(command, 10.0)
    response = send_session_command(
        command.session,
        command.model_dump(mode="json", by_alias=True),
        timeout=timeout,
    )
    emit_document(response)
    if response.get("type") == "error":
        code = response.get("code")
        return 2 if code in {"invalid_input", "invalid_cli_command"} else 1
    return 0
