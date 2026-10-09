from __future__ import annotations

import gzip
import tempfile
import tracemalloc
import unittest
from pathlib import Path

from xui_lab.contracts import RuntimeExchangeEvent
from xui_lab.io import read_json
from xui_lab.trace import EventTrace


class EventTraceTests(unittest.TestCase):
    def test_preserves_each_exchange_before_the_response_is_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event-trace.json.gz"
            trace = EventTrace(path)
            command = {"op": "query", "kind": "tree"}
            response = {"ok": True, "result": {"value": "before"}}
            trace.append(command, response)
            response["result"]["value"] = "after"
            trace.append(command, response)
            trace.close()
            trace.close()

            events = [RuntimeExchangeEvent.model_validate(e) for e in read_json(path)]
            self.assertEqual([0, 1], [e.sequence for e in events])
            self.assertEqual(["query", "query"], [e.operation for e in events])
            self.assertEqual({"schemaVersion": 1, **command}, events[0].command)
            self.assertEqual("before", events[0].response["result"]["value"])
            self.assertEqual(response, events[1].response)

    def test_empty_trace_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event-trace.json.gz"
            EventTrace(path).close()
            self.assertEqual([], read_json(path))

    def test_repeated_large_widget_trees_have_bounded_memory_and_disk(self) -> None:
        # Studio repeatedly resolves controls against a deeply nested 1,931-node tree.
        tree = {
            "path": "/root",
            "children": [
                {
                    "control_id": f"control-{index}",
                    "path": "/root/panel/section/scroll/content" * 6 + f"/row-{index}",
                    "class": "LLButton",
                    "visible": True,
                    "value": index,
                    "screen_rect": {"left": 0, "right": 320, "top": 40, "bottom": 0},
                    "children": [],
                }
                for index in range(1931)
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event-trace.json.gz"
            tracemalloc.start()
            try:
                trace = EventTrace(path)
                try:
                    for index in range(32):
                        tree["children"][0]["value"] = index
                        trace.append(
                            {"op": "query", "kind": "tree"},
                            {"ok": True, "result": tree},
                        )
                finally:
                    trace.close()
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()

            with gzip.open(path, "rb") as stream:
                uncompressed = 0
                while block := stream.read(1024 * 1024):
                    uncompressed += len(block)
            self.assertGreater(uncompressed, 20 * 1024 * 1024)
            self.assertLess(path.stat().st_size, 1024 * 1024)
            self.assertLess(peak, 4 * 1024 * 1024)
