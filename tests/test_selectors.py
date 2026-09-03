"""Selector ranking and user-visible locator tests."""

from __future__ import annotations

import unittest

from xui_lab.errors import AssertionFailure
from xui_lab.operations import label_selector, role_selector
from xui_lab.selectors import (
    explain_ranked_locator,
    match_nodes,
    rank_locator,
    require_unique,
)


def node(
    *,
    path: str,
    control_id: str,
    runtime_class: str,
    label: str | None = None,
    placeholder: str | None = None,
    model_id: str | None = None,
    visible_chain: bool = True,
    enabled_chain: bool = True,
    value: object = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "path": path,
        "control_id": control_id,
        "class": runtime_class,
        "visible_chain": visible_chain,
        "enabled_chain": enabled_chain,
        "children": [],
    }
    if label is not None:
        result["label"] = label
    if placeholder is not None:
        result["placeholder"] = placeholder
    if model_id is not None:
        result["model_id"] = model_id
    if value is not None:
        result["value"] = value
    return result


class SelectorTests(unittest.TestCase):
    def test_ranking_prefers_role_and_label_over_control_id(self) -> None:
        tree = {
            "path": "/root",
            "control_id": "root",
            "class": "LLPanel",
            "visible_chain": True,
            "children": [
                node(
                    path="/root/ok",
                    control_id="btn-ok",
                    runtime_class="LLButton",
                    label="OK",
                )
            ],
        }
        ranked = rank_locator(tree["children"][0], tree)
        self.assertEqual("role", ranked.kind)
        self.assertEqual("window.get_by_role('button', name='OK')", ranked.python)
        self.assertEqual(
            {
                "schemaVersion": 1,
                "kind": "role",
                "role": "button",
                "name": "OK",
            },
            ranked.selector.model_dump(mode="json", by_alias=True),
        )
        self.assertIsNone(ranked.fallback_reason)

    def test_duplicate_labels_fall_back_to_control_id(self) -> None:
        tree = {
            "path": "/root",
            "control_id": "root",
            "class": "LLPanel",
            "visible_chain": True,
            "children": [
                node(
                    path="/root/one",
                    control_id="one",
                    runtime_class="LLButton",
                    label="Save",
                ),
                node(
                    path="/root/two",
                    control_id="two",
                    runtime_class="LLButton",
                    label="Save",
                ),
            ],
        }
        ranked = rank_locator(tree["children"][0], tree)
        self.assertEqual("controlId", ranked.kind)
        self.assertEqual("no unique user-visible name", ranked.fallback_reason)
        self.assertEqual(1, ranked.match_count)
        self.assertEqual(
            "# locator: signals=controlId; matches=1; "
            "fallback=no unique user-visible name",
            explain_ranked_locator(ranked),
        )

    def test_hidden_controls_do_not_match_label_locators(self) -> None:
        tree = {
            "path": "/root",
            "control_id": "root",
            "class": "LLPanel",
            "visible_chain": True,
            "children": [
                node(
                    path="/root/hidden",
                    control_id="hidden",
                    runtime_class="LLButton",
                    label="OK",
                    visible_chain=False,
                )
            ],
        }
        self.assertEqual([], match_nodes(tree, label_selector("OK")))
        with self.assertRaises(AssertionFailure):
            require_unique(tree, role_selector("button", "OK"))

    def test_model_id_is_used_when_generated_siblings_share_a_path(self) -> None:
        model_id = "11111111-1111-1111-1111-111111111111"
        tree = {
            "path": "/root",
            "control_id": "root",
            "class": "LLPanel",
            "visible_chain": True,
            "children": [
                node(
                    path="/root/row",
                    control_id="row-1",
                    runtime_class="LLTextBox",
                    model_id=model_id,
                    label="Known Notecard",
                )
            ],
        }
        ranked = rank_locator(tree["children"][0], tree)
        self.assertEqual("role", ranked.kind)
        self.assertIn("Known Notecard", ranked.python)


if __name__ == "__main__":
    unittest.main()
