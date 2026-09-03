"""State-machine coverage for persistent CLI state."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
)

from xui_lab.contracts import ReplayCliCommand, parse_cli_command
from xui_lab.recording import _cli_payload, parse_recording, recording_from_runtime
from xui_lab.session import (
    SessionFile,
    cleanup_stale,
    list_sessions,
    remove_session,
    write_session,
)

SESSION_IDS = st.sampled_from(("sess_a", "sess_b", "sess_c"))
STATUSES = st.sampled_from(("starting", "ready", "closed"))
DEAD_PID = 2**31 - 2
TREE = {
    "control_id": "root",
    "path": "/root",
    "class": "LLPanel",
    "visible_chain": True,
    "enabled_chain": True,
    "children": [
        {
            "control_id": "button",
            "path": "/root/button",
            "class": "LLButton",
            "label": "OK",
            "visible_chain": True,
            "enabled_chain": True,
            "children": [],
        }
    ],
}


class SessionStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.temporary = tempfile.TemporaryDirectory(prefix="xui-state-", dir="/tmp")
        self.previous_runtime_dir = os.environ.get("XUI_LAB_RUNTIME_DIR")
        os.environ["XUI_LAB_RUNTIME_DIR"] = self.temporary.name
        self.expected: dict[str, SessionFile] = {}

    def teardown(self) -> None:
        if self.previous_runtime_dir is None:
            os.environ.pop("XUI_LAB_RUNTIME_DIR", None)
        else:
            os.environ["XUI_LAB_RUNTIME_DIR"] = self.previous_runtime_dir
        self.temporary.cleanup()

    def make_record(self, session_id: str, status: str, pid: int | None) -> SessionFile:
        return SessionFile(
            schemaVersion=1,
            sessionId=session_id,
            token="token",
            status=status,
            socketPath=str(Path(self.temporary.name) / f"{session_id}.sock"),
            subject="test_widgets",
            runtime="/runtime",
            source="/source",
            fork="alchemy",
            artifacts="/artifacts",
            requestId="req_state",
            width=800,
            height=600,
            uiScale=1.0,
            capabilities=("input",),
            viewerSource=(),
            pid=pid,
        )

    @rule(
        session_id=SESSION_IDS,
        status=STATUSES,
        live=st.booleans(),
        has_pid=st.booleans(),
    )
    def write_or_retry(
        self, session_id: str, status: str, live: bool, has_pid: bool
    ) -> None:
        pid = os.getpid() if live else DEAD_PID
        record = self.make_record(session_id, status, pid if has_pid else None)
        write_session(record)
        write_session(record)
        self.expected[session_id] = record

    @rule(session_id=SESSION_IDS)
    def cancel(self, session_id: str) -> None:
        remove_session(session_id)
        remove_session(session_id)
        self.expected.pop(session_id, None)

    @rule()
    def clean_stale(self) -> None:
        with patch(
            "xui_lab.session.pid_alive", side_effect=lambda pid: pid == os.getpid()
        ):
            removed = set(cleanup_stale())
        expected_removed = {
            session_id
            for session_id, record in self.expected.items()
            if (record.status == "ready" and record.pid != os.getpid())
            or (
                record.status == "starting"
                and record.pid is not None
                and record.pid != os.getpid()
            )
        }
        assert removed == expected_removed
        for session_id in expected_removed:
            self.expected.pop(session_id)

    @precondition(lambda self: bool(self.expected))
    @rule(data=st.data())
    def retry_from_disk(self, data: Any) -> None:
        session_id = data.draw(st.sampled_from(sorted(self.expected)))
        write_session(self.expected[session_id])

    @rule(
        action=st.sampled_from(("click", "fill", "scroll")),
        text=st.text(max_size=12),
        clicks=st.integers(-5, 5).filter(lambda value: value != 0),
    )
    def recording_round_trip(self, action: str, text: str, clicks: int) -> None:
        runtime_action: dict[str, Any] = {
            "action": action,
            "controlId": "button",
        }
        if action == "fill":
            runtime_action["text"] = text
        if action == "scroll":
            runtime_action["clicks"] = clicks
        recording = recording_from_runtime([runtime_action], TREE)
        parsed = parse_recording(recording.model_dump(mode="json", by_alias=True))
        replay = ReplayCliCommand(
            schemaVersion=1,
            command="replay",
            fork=None,
            viewerSource=(),
            requestId="req_replay",
            timeout=None,
            jq=None,
            file="recording.json",
            session="sess_target",
        )
        command = parse_cli_command(_cli_payload(parsed.commands[0], replay, 1))
        assert command.command == action
        assert command.request_id == "req_replay_1"

    @invariant()
    def session_store_matches_model(self) -> None:
        observed = {record.session_id: record for record in list_sessions()}
        assert observed == self.expected


TestSessionStateMachine = SessionStateMachine.TestCase
TestSessionStateMachine.settings = settings(
    max_examples=30, stateful_step_count=20, deadline=None
)
