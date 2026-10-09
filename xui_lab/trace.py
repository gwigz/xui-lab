"""Stream runtime exchanges without retaining previous widget trees."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from .contracts import SCHEMA_VERSION, RuntimeExchangeEvent


class EventTrace:
    def __init__(self, path: Path):
        self.path = path
        self._stream = gzip.open(path, "wt", encoding="utf-8", compresslevel=6)
        self._stream.write("[")
        self._sequence = 0

    def append(self, command: dict[str, Any], response: dict[str, Any]) -> None:
        event = RuntimeExchangeEvent(
            schemaVersion=SCHEMA_VERSION,
            type="event",
            event="runtimeExchange",
            sequence=self._sequence,
            operation=str(command.get("op", "unknown")),
            command={"schemaVersion": SCHEMA_VERSION, **command},
            response=response,
        )
        self._stream.write(",\n" if self._sequence else "\n")
        json.dump(
            event.model_dump(mode="json", by_alias=True, exclude_none=True),
            self._stream,
            separators=(",", ":"),
            sort_keys=True,
        )
        self._sequence += 1

    def close(self) -> None:
        if not self._stream.closed:
            try:
                self._stream.write("\n]\n")
            finally:
                self._stream.close()
