import { describe, expect, it } from "vitest";
import { parseInspectorState } from "./contracts";
import { OPENAPI_HASH } from "./generated/openapi-hash";
import { filterTreeRoots } from "./tree-filter";

const state = parseInspectorState({
  tree: {
    control_id: "root",
    path: "",
    class: "LLPanel",
    visible_chain: true,
    children: [
      {
        control_id: "menu-holder",
        path: "/Menu Holder",
        class: "LLMenuHolderGL",
        visible_chain: true,
        children: [
          {
            control_id: "inventory-menu",
            path: "/Menu Holder/Inventory",
            class: "LLMenuGL",
            visible_chain: false,
            children: [],
          },
        ],
      },
      {
        control_id: "floater-view",
        path: "/Floater View",
        class: "LLFloaterView",
        visible_chain: true,
        children: [
          {
            control_id: "subject",
            path: "/Floater View/floater_inventory",
            class: "LLFloater",
            visible_chain: true,
            children: [
              {
                control_id: "visible-button",
                path: "/Floater View/floater_inventory/visible",
                class: "LLButton",
                visible_chain: true,
                children: [],
              },
              {
                control_id: "hidden-button",
                path: "/Floater View/floater_inventory/hidden",
                class: "LLButton",
                visible_chain: false,
                children: [],
              },
            ],
          },
        ],
      },
    ],
  },
  diagnostics: {
    subject: { view: { path: "/Floater View/floater_inventory" } },
  },
  recording: [],
  locators: {},
  artifactDir: "/tmp/artifacts",
  subject: "inventory_explorer",
  fixture: "inventory_explorer",
  subjects: ["inventory_explorer"],
  fixtures: ["inventory_explorer"],
  scenarios: [],
  inputOperations: [],
  capture: { available: false, version: 0 },
  captures: [],
  stateVersion: 1,
  openapiHash: OPENAPI_HASH,
});

const defaults = {
  showHidden: false,
  showLabRoots: false,
  showMenus: false,
};

describe("filterTreeRoots", () => {
  it("defaults to the visible production subject subtree", () => {
    const roots = filterTreeRoots(state, defaults, "");

    expect(roots.map((root) => root.controlId)).toEqual(["subject"]);
    expect(roots[0]?.children.map((child) => child.controlId)).toEqual(["visible-button"]);
  });

  it("shows hidden controls, menus, and lab roots independently", () => {
    const hidden = filterTreeRoots(state, { ...defaults, showHidden: true }, "");
    expect(hidden[0]?.children.map((child) => child.controlId)).toEqual([
      "visible-button",
      "hidden-button",
    ]);

    const menus = filterTreeRoots(state, { ...defaults, showHidden: true, showMenus: true }, "");
    expect(menus.map((root) => root.controlId)).toEqual(["subject", "menu-holder"]);

    const labRoots = filterTreeRoots(state, { ...defaults, showLabRoots: true }, "");
    expect(labRoots.map((root) => root.controlId)).toEqual(["root"]);
    expect(labRoots[0]?.children.map((child) => child.controlId)).toEqual(["floater-view"]);
  });

  it("retains a selected hidden control and its ancestors", () => {
    const roots = filterTreeRoots(state, defaults, "hidden-button");

    expect(roots[0]?.children.map((child) => child.controlId)).toEqual([
      "visible-button",
      "hidden-button",
    ]);
  });
});
