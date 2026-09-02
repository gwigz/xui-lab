import { describe, expect, it } from "vitest";
import {
  findTreeNodeAtPoint,
  findTreeNodeByControlId,
  parseActionResponse,
  parseInspectorState,
  treeNodeVisibleRect,
} from "./contracts";

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

describe("findTreeNodeAtPoint", () => {
  it("chooses the smallest visible clipped element under the pointer", () => {
    const state = parseInspectorState({
      ...validState,
      tree: {
        ...validState.tree,
        visible_chain: true,
        screen_rect: { left: 0, right: 800, bottom: 0, top: 600 },
        clipping_rect: { left: 0, right: 800, bottom: 0, top: 600 },
        children: [
          {
            control_id: "panel",
            path: "/root/panel",
            class: "LLPanel",
            visible_chain: true,
            screen_rect: { left: 100, right: 500, bottom: 100, top: 400 },
            clipping_rect: { left: 100, right: 450, bottom: 100, top: 400 },
            children: [
              {
                control_id: "save-button",
                path: "/root/panel/save",
                label: "Save",
                class: "LLButton",
                visible_chain: true,
                screen_rect: { left: 350, right: 475, bottom: 150, top: 200 },
                clipping_rect: { left: 350, right: 450, bottom: 150, top: 200 },
                children: [],
              },
            ],
          },
          {
            control_id: "hidden-overlay",
            path: "/root/hidden-overlay",
            class: "LLPanel",
            visible_chain: false,
            screen_rect: { left: 0, right: 800, bottom: 0, top: 600 },
            clipping_rect: { left: 0, right: 800, bottom: 0, top: 600 },
            children: [],
          },
        ],
      },
    });

    const target = findTreeNodeAtPoint(state.tree, { x: 425, y: 175 });

    expect(target?.controlId).toBe("save-button");
    expect(target === undefined ? undefined : treeNodeVisibleRect(target)).toEqual({
      left: 350,
      right: 450,
      bottom: 150,
      top: 200,
    });
    expect(findTreeNodeAtPoint(state.tree, { x: 460, y: 175 })?.controlId).toBe("root");
  });
});
