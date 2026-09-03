"""Local authenticated sessions for one-shot CLI commands."""

from __future__ import annotations

import json
import os
import signal
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from platformdirs import user_runtime_dir
from pydantic import Field

from .contracts import SCHEMA_VERSION, ContractModel, FrozenTuple, parse_cli_command
from .errors import InputError, RuntimeFailure, XUILabError
from .io import write_json

ENV_RUNTIME_DIR = "XUI_LAB_RUNTIME_DIR"
READY_POLL_SECONDS = 0.05


class SessionFile(ContractModel):
    schema_version: int = Field(alias="schemaVersion")
    session_id: str = Field(alias="sessionId")
    token: str
    status: str
    socket_path: str = Field(alias="socketPath")
    subject: str
    runtime: str
    source: str
    fork: str
    artifacts: str
    request_id: str = Field(alias="requestId")
    width: int
    height: int
    ui_scale: float = Field(alias="uiScale")
    capabilities: FrozenTuple[str]
    viewer_source: FrozenTuple[str] = Field(alias="viewerSource")
    fixture: str | None = None
    pid: int | None = None
    viewer_pid: int | None = Field(default=None, alias="viewerPid")
    fork_commit: str | None = Field(default=None, alias="forkCommit")
    error: str | None = None


def runtime_dir() -> Path:
    override = os.environ.get(ENV_RUNTIME_DIR)
    root = (
        Path(override).expanduser() if override else Path(user_runtime_dir("xui-lab"))
    )
    path = root / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    os.chmod(path, 0o700)
    return path


def session_path(session_id: str) -> Path:
    return runtime_dir() / f"{session_id}.json"


def socket_path(session_id: str) -> Path:
    return runtime_dir() / f"{session_id}.sock"


def write_session(record: SessionFile) -> None:
    path = session_path(record.session_id)
    write_json(
        path,
        record.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
    os.chmod(path, 0o600)


def read_session(session_id: str) -> SessionFile:
    path = session_path(session_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise InputError(f"session not found: {session_id}") from error
    except json.JSONDecodeError as error:
        raise InputError(f"session record is invalid: {session_id}") from error
    return SessionFile.model_validate(payload)


def list_sessions() -> list[SessionFile]:
    records = []
    for path in sorted(runtime_dir().glob("*.json")):
        try:
            records.append(
                SessionFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
            )
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return records


def pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cleanup_stale() -> list[str]:
    removed: list[str] = []
    for record in list_sessions():
        if record.status == "ready" and not pid_alive(record.pid):
            remove_session(record.session_id)
            removed.append(record.session_id)
        elif (
            record.status == "starting"
            and record.pid is not None
            and not pid_alive(record.pid)
        ):
            remove_session(record.session_id)
            removed.append(record.session_id)
    return removed


def remove_session(session_id: str) -> None:
    path = session_path(session_id)
    sock = socket_path(session_id)
    path.unlink(missing_ok=True)
    sock.unlink(missing_ok=True)


def wait_until_ready(session_id: str, timeout: float) -> SessionFile:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            record = read_session(session_id)
        except InputError:
            time.sleep(READY_POLL_SECONDS)
            continue
        if record.status == "ready" and record.socket_path:
            return record
        if record.status == "closed" or record.error:
            raise RuntimeFailure(record.error or f"session failed: {session_id}")
        time.sleep(READY_POLL_SECONDS)
    raise RuntimeFailure(f"session {session_id} did not become ready")


def send_session_command(
    session_id: str,
    command: dict[str, Any],
    *,
    timeout: float,
    token: str | None = None,
) -> dict[str, Any]:
    record = read_session(session_id)
    if record.status != "ready":
        raise InputError(f"session is not ready: {session_id}")
    payload = {
        "token": token or record.token,
        "command": command,
    }
    deadline = time.monotonic() + timeout
    sock: socket.socket | None = None
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(max(0.05, deadline - time.monotonic()))
        try:
            sock.connect(record.socket_path)
            break
        except OSError as error:
            last_error = error
            sock.close()
            sock = None
            time.sleep(0.05)
    if sock is None:
        raise RuntimeFailure(
            f"session {session_id} did not respond: {last_error}"
        ) from last_error
    try:
        sock.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
        chunks = bytearray()
        while True:
            piece = sock.recv(65536)
            if not piece:
                break
            chunks.extend(piece)
            if b"\n" in piece:
                break
    except OSError as error:
        raise RuntimeFailure(
            f"session {session_id} did not respond: {error}"
        ) from error
    finally:
        sock.close()
    line = bytes(chunks).decode("utf-8").splitlines()[0] if chunks else ""
    if not line:
        raise RuntimeFailure(f"session {session_id} closed the connection")
    try:
        response = json.loads(line)
    except json.JSONDecodeError as error:
        raise RuntimeFailure(f"session {session_id} returned invalid JSON") from error
    if not isinstance(response, dict):
        raise RuntimeFailure(f"session {session_id} returned a non-object response")
    return response


def serve_until_closed(
    record: SessionFile,
    handler: Callable[[Any], dict[str, Any]],
    *,
    on_ready: Callable[[int], None] | None = None,
) -> None:
    sock_path = Path(record.socket_path)
    sock_path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    os.chmod(sock_path, 0o600)
    server.listen(8)
    server.settimeout(1.0)
    if on_ready is not None:
        on_ready(os.getpid())
    closed = False
    try:
        while not closed:
            try:
                conn, _unused = server.accept()
            except TimeoutError:
                if record.pid is not None and not pid_alive(record.pid):
                    break
                continue
            with conn:
                conn.settimeout(30.0)
                data = bytearray()
                while b"\n" not in data:
                    piece = conn.recv(65536)
                    if not piece:
                        break
                    data.extend(piece)
                if not data:
                    continue
                try:
                    request = json.loads(data.decode("utf-8").splitlines()[0])
                except json.JSONDecodeError:
                    conn.sendall(
                        json.dumps(
                            {
                                "schemaVersion": SCHEMA_VERSION,
                                "type": "error",
                                "code": "invalid_input",
                                "message": "session request is not JSON",
                                "operation": "session",
                                "retryable": False,
                            },
                            separators=(",", ":"),
                        ).encode("utf-8")
                        + b"\n"
                    )
                    continue
                if request.get("token") != record.token:
                    conn.sendall(
                        json.dumps(
                            {
                                "schemaVersion": SCHEMA_VERSION,
                                "type": "error",
                                "code": "invalid_input",
                                "message": "session token is invalid",
                                "operation": "session",
                                "retryable": False,
                            },
                            separators=(",", ":"),
                        ).encode("utf-8")
                        + b"\n"
                    )
                    continue
                command_data = request.get("command")
                operation = "session"
                request_id = None
                if isinstance(command_data, dict):
                    raw_operation = command_data.get("command")
                    if isinstance(raw_operation, str):
                        operation = raw_operation
                    raw_request_id = command_data.get("requestId")
                    if isinstance(raw_request_id, str):
                        request_id = raw_request_id
                try:
                    command = parse_cli_command(command_data)
                    response = handler(command)
                    if (
                        getattr(command, "command", None) == "session"
                        and getattr(command, "session_command", None) == "close"
                    ):
                        closed = True
                except XUILabError as error:
                    from .contracts import error_record

                    response = error_record(
                        error, operation=operation, request_id=request_id
                    ).model_dump(mode="json", by_alias=True, exclude_none=True)
                conn.sendall(
                    json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
                )
    finally:
        server.close()
        sock_path.unlink(missing_ok=True)


def terminate_pid(pid: int | None) -> bool:
    if not pid_alive(pid):
        return False
    assert pid is not None
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    if pid_alive(pid):
        os.kill(pid, signal.SIGKILL)
    return True
