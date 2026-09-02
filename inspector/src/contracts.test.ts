import { describe, expect, it } from "vitest";
import { findTreeNodeByControlId, parseActionResponse, parseInspectorState } from "./contracts";

const validState = {
  tree: {
    control_id: "root",
    path: "/root",
    class: "LLView",
    children: [
      {
        control_id: "save-button",
        path: "/root/button",
        name: "Save",
        class: "8LLButton",
        children: [],
      },
    ],
  },
  diagnostics: { processId: 42 },
  recording: ["window.get_by_path('/root/button').click()"],
  artifactDir: "/tmp/artifacts",
  subjects: ["test_widgets"],
  fixtures: [],
  scenarios: ["test_floater"],
  inputOperations: ["click", "drag", "fill"],
  capture: { available: true, version: 2 },
};

describe("parseInspectorState", () => {
  it("constructs the typed client model at the HTTP boundary", () => {
    const state = parseInspectorState(validState);

    expect(state.capture).toEqual({ kind: "available", version: 2 });
    expect(state.inputOperations).toEqual(["click", "drag", "fill"]);
    expect(findTreeNodeByControlId(state.tree, "save-button")?.title).toBe("Save · LLButton");
  });

  it("rejects malformed server data", () => {
    expect(() => parseInspectorState({ ...validState, recording: "not an array" })).toThrow(
      "state.recording must be an array",
    );
  });

  it("keeps controls distinct when generated controls share one XUI path", () => {
    const state = parseInspectorState({
      ...validState,
      tree: {
        ...validState.tree,
        children: [
          {
            control_id: "top-left",
            path: "/root/resize_handle",
            class: "14LLResizeHandle",
            children: [],
          },
          {
            control_id: "bottom-right",
            path: "/root/resize_handle",
            class: "14LLResizeHandle",
            children: [],
          },
        ],
      },
    });

    expect(findTreeNodeByControlId(state.tree, "top-left")?.controlId).toBe("top-left");
    expect(findTreeNodeByControlId(state.tree, "bottom-right")?.controlId).toBe("bottom-right");
  });
});

describe("parseActionResponse", () => {
  it("returns successful action data", () => {
    expect(parseActionResponse({ ok: true, result: { handled: true } })).toEqual({ handled: true });
  });

  it("turns API failures into errors", () => {
    expect(() => parseActionResponse({ ok: false, error: "not found" })).toThrow("not found");
  });
});
