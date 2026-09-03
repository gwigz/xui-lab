"""JSON-lines transport for a fork runtime process."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any, TextIO

from .contracts import (
    RuntimeError,
    RuntimeSuccess,
    parse_runtime_command,
    parse_runtime_response,
    parse_runtime_result,
)
from .errors import InputError, RuntimeFailure, problem_summary


class RuntimeProcess:
    def __init__(
        self,
        executable: Path,
        stderr_path: Path,
        *,
        mode: str = "scenario",
        request_timeout: float = 10.0,
        shutdown_timeout: float = 10.0,
    ):
        if mode not in {"scenario", "interactive"}:
            raise RuntimeFailure(f"unknown runtime process mode: {mode}")
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr: TextIO = stderr_path.open("w", encoding="utf-8")
        self._request_timeout = request_timeout
        self._shutdown_timeout = shutdown_timeout
        self._responses: queue.Queue[str | None] = queue.Queue()
        self._failed = False
        self._closed = False
        self._status: int | None = None
        try:
            self._process = subprocess.Popen(
                [str(executable), f"--{mode}"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                bufsize=1,
            )
        except OSError as error:
            self._stderr.close()
            raise RuntimeFailure(
                f"cannot start runtime {executable}: {error}"
            ) from error
        if self._process.stdin is None or self._process.stdout is None:
            self._terminate()
            self._stderr.close()
            raise RuntimeFailure("runtime process has no JSON-lines pipes")
        self._reader = threading.Thread(
            target=self._read_responses, name="xui-lab-runtime-reader", daemon=True
        )
        self._reader.start()

    @property
    def pid(self) -> int:
        return self._process.pid

    def _read_responses(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                self._responses.put(line)
        finally:
            self._responses.put(None)

    def request(
        self, command: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        candidate = {"schemaVersion": 1, **command}
        validated_command = parse_runtime_command(candidate)
        operation = validated_command.op
        command_data = validated_command.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        if self._closed:
            raise RuntimeFailure("runtime process is closed")
        if self._failed:
            raise RuntimeFailure(
                "runtime process cannot accept requests after a protocol failure"
            )
        if self._process.poll() is not None:
            self._failed = True
            raise RuntimeFailure(
                f"runtime exited with status {self._process.returncode} before '{operation}'"
            )
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(
                json.dumps(command_data, separators=(",", ":")) + "\n"
            )
            self._process.stdin.flush()
        except OSError as error:
            self._failed = True
            status = self._process.poll()
            if status is not None:
                raise RuntimeFailure(
                    f"runtime exited with status {status} during '{operation}'"
                ) from error
            raise RuntimeFailure(
                f"runtime closed its request stream during '{operation}'"
            ) from error

        wait_seconds = self._request_timeout if timeout is None else timeout
        try:
            line = self._responses.get(timeout=wait_seconds)
        except queue.Empty as error:
            self._failed = True
            status = self._process.poll()
            if status is not None:
                raise RuntimeFailure(
                    f"runtime exited with status {status} before responding to '{operation}'"
                ) from error
            raise RuntimeFailure(
                f"runtime stalled for {wait_seconds:g}s waiting for response to '{operation}'"
            ) from error

        if line is None:
            self._failed = True
            status = self._process.poll()
            if status is not None:
                raise RuntimeFailure(
                    f"runtime exited with status {status} before responding to '{operation}'"
                )
            raise RuntimeFailure(
                f"runtime closed its response stream while still running during '{operation}'"
            )
        try:
            response_data = json.loads(line)
        except json.JSONDecodeError as error:
            self._failed = True
            raise RuntimeFailure(
                f"runtime returned an invalid response to '{operation}': invalid JSON: {line.rstrip()}"
            ) from error
        try:
            response = parse_runtime_response(response_data, operation)
        except InputError as error:
            self._failed = True
            raise RuntimeFailure(
                f"runtime returned an invalid response to '{operation}': "
                f"{problem_summary(error)}"
            ) from error
        if isinstance(response, RuntimeError):
            raise RuntimeFailure(f"{response.error.code}: {response.error.message}")
        assert isinstance(response, RuntimeSuccess)
        try:
            result = parse_runtime_result(response.result, operation)
        except InputError as error:
            self._failed = True
            raise RuntimeFailure(
                f"runtime returned an invalid result for '{operation}': "
                f"{problem_summary(error)}"
            ) from error
        return {"ok": True, "result": result}

    def _terminate(self) -> int:
        status = self._process.poll()
        if status is not None:
            return status
        self._process.terminate()
        try:
            return self._process.wait(timeout=self._shutdown_timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            try:
                return self._process.wait(timeout=self._shutdown_timeout)
            except subprocess.TimeoutExpired as error:
                raise RuntimeFailure(
                    "runtime did not exit after terminate and kill"
                ) from error

    def _close_streams(self) -> None:
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        if self._process.stdout is not None:
            self._process.stdout.close()
        self._reader.join(timeout=self._shutdown_timeout)
        self._stderr.close()

    def close(self) -> int:
        if self._closed:
            assert self._status is not None
            return self._status

        failure: RuntimeFailure | None = None
        status = self._process.poll()
        if status is None and not self._failed:
            try:
                self.request({"op": "shutdown"}, timeout=self._shutdown_timeout)
            except RuntimeFailure as error:
                failure = error
            else:
                try:
                    status = self._process.wait(timeout=self._shutdown_timeout)
                except subprocess.TimeoutExpired:
                    failure = RuntimeFailure(
                        f"runtime stalled for {self._shutdown_timeout:g}s during shutdown after acknowledging the request"
                    )

        if status is None:
            status = self._terminate()
        self._status = status
        self._close_streams()
        self._closed = True
        if failure is not None:
            raise failure
        return status

    def __enter__(self) -> RuntimeProcess:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()
