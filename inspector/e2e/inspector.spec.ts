import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page, test } from "@playwright/test";
import { OPENAPI_HASH } from "../src/generated/openapi-hash";

const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);
const largePng = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "fixtures/capture.png"),
);

const inspectorState = {
  tree: {
    control_id: "root",
    path: "",
    class: "LLView",
    visible_chain: true,
    children: [
      {
        control_id: "menu-holder",
        path: "/Menu Holder",
        name: "Menu Holder",
        class: "LLMenuHolderGL",
        visible_chain: true,
        children: [
          {
            control_id: "inventory-menu",
            path: "/Menu Holder/Inventory",
            name: "Inventory menu",
            class: "LLMenuGL",
            visible_chain: true,
            children: [],
          },
        ],
      },
      {
        control_id: "floater-view",
        path: "/Floater View",
        name: "Floater View",
        class: "LLFloaterView",
        visible_chain: true,
        children: [
          {
            control_id: "subject",
            path: "/Floater View/test_widgets",
            name: "Test widgets",
            class: "LLFloater",
            visible_chain: true,
            children: [
              {
                control_id: "save-button",
                path: "/Floater View/test_widgets/button",
                name: "Save",
                class: "8LLButton",
                visible_chain: true,
                children: [],
              },
              {
                control_id: "hidden-button",
                path: "/Floater View/test_widgets/hidden",
                name: "Hidden action",
                class: "8LLButton",
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
    processId: 42,
    viewport: { lluiWidth: 800, lluiHeight: 600, windowWidth: 800, windowHeight: 600, uiScale: 1 },
    subject: { view: { path: "/Floater View/test_widgets" } },
  },
  recording: ["window.get_by_role('button', name='Save').click()"],
  locators: {
    "save-button": {
      selector: { schemaVersion: 1, kind: "role", role: "button", name: "Save" },
      python: "window.get_by_role('button', name='Save')",
      kind: "role",
      matchCount: 1,
      signals: ["role", "name"],
      fallbackReason: null,
    },
  },
  artifactDir: "/tmp/artifacts",
  subject: "test_widgets",
  fixture: "",
  subjects: ["test_widgets"],
  fixtures: [],
  scenarios: ["test_floater"],
  inputOperations: ["click", "drag", "fill"],
  capture: { available: true, version: 2 },
  captures: [
    {
      version: 1,
      sequence: 1,
      action: "initial",
      name: "interactive-0001-initial",
      label: "800×600 · 1× · no fixture · Default",
    },
    {
      version: 2,
      sequence: 2,
      action: "click",
      name: "interactive-0002-click",
      label: "800×600 · 1× · no fixture · Default",
    },
  ],
  stateVersion: 4,
  openapiHash: OPENAPI_HASH,
};

async function mockInspectorApi(
  page: Page,
  actions: unknown[],
  options: Readonly<{
    state?: typeof inspectorState;
    capturePng?: Buffer;
  }> = {},
): Promise<void> {
  const state = options.state ?? inspectorState;
  const capturePng = options.capturePng ?? png;
  await page.addInitScript(() => {
    class StubEventSource {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      readyState = 1;
      url: string;
      withCredentials = false;
      onerror: ((this: EventSource, ev: Event) => unknown) | null = null;
      onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null;
      onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
      constructor(url: string | URL) {
        this.url = String(url);
      }
      addEventListener(): void {}
      removeEventListener(): void {}
      close(): void {
        this.readyState = 2;
      }
      dispatchEvent(): boolean {
        return false;
      }
    }
    Object.defineProperty(window, "EventSource", { configurable: true, value: StubEventSource });
  });
  await page.route("**/api/v1/state", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(state),
    });
  });
  await page.route("**/api/v1/captures/**/snapshot", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        version: 1,
        sequence: 1,
        action: "initial",
        name: "interactive-0001-initial",
        label: "800×600 · 1× · no fixture · Default",
        tree: state.tree,
        diagnostics: state.diagnostics,
        recording: state.recording,
        locators: state.locators,
      }),
    });
  });
  await page.route("**/api/v1/captures/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/png", body: capturePng });
  });
  await page.route("**/api/v1/actions", async (route) => {
    const posted: unknown = route.request().postDataJSON();
    actions.push(posted);
    const action =
      typeof posted === "object" && posted !== null && "action" in posted
        ? posted.action
        : "unknown";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, result: { accepted: true, action } }),
    });
  });
}

test("renders the production tree and capture from the inspector API", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => {
    pageErrors.push(String(error));
  });
  const actions: unknown[] = [];
  await mockInspectorApi(page, actions);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Save · LLButton" })).toBeVisible();
  await expect(page.getByRole("img", { name: "xui-lab screenshot" })).toBeVisible();
  await expect(page.getByText("/tmp/artifacts")).toHaveCount(0);
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Display" })).toBeVisible();
  await expect(page.getByLabel("Viewport width")).toBeVisible();
  await expect(page.getByLabel("Subject width")).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test("applies subject-size and UI-scale comparison presets", async ({ page }) => {
  const actions: unknown[] = [];
  await mockInspectorApi(page, actions);
  await page.goto("/");
  await page.getByRole("button", { name: "Settings" }).click();

  await page.getByRole("button", { name: "Narrow 360 × 580" }).click();
  await expect
    .poll(() => actions.at(-1))
    .toMatchObject({
      schemaVersion: 1,
      action: "resizeSubject",
      width: 360,
      height: 580,
    });

  await page.getByRole("button", { name: "UI scale 1.25×" }).click();
  await expect
    .poll(() => actions.at(-1))
    .toMatchObject({
      schemaVersion: 1,
      action: "resizeViewport",
      width: 1000,
      height: 750,
      uiScale: 1.25,
    });
});

test("compares a capture with a local reference image without affecting the session", async ({
  page,
}) => {
  const actions: unknown[] = [];
  await mockInspectorApi(page, actions);
  await page.goto("/");

  await page.locator('input[type="file"][accept="image/*"]').setInputFiles({
    name: "inventory-reference.png",
    mimeType: "image/png",
    buffer: largePng,
  });

  const reference = page.getByRole("img", { name: "Reference: inventory-reference.png" });
  await expect(reference).toBeVisible();
  await expect.poll(() => reference.evaluate((image) => image.naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByText("Visual aid only")).toBeVisible();
  await expect(page.getByRole("button", { name: "Side by side" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await page.getByRole("button", { name: "Overlay" }).click();
  const opacity = page.getByRole("slider", { name: "Opacity" });
  await expect(opacity).toBeVisible();
  await expect(page.locator('[data-slot="slider-control"]')).toBeVisible();
  await expect(page.locator('[data-slot="slider-value"]')).toContainText("50");
  await expect(page.locator('[data-slot="slider-control"] input[type="range"]')).toHaveCount(1);
  await opacity.press("ArrowRight");
  await expect(opacity).toHaveValue("55");
  await expect(page.locator('[data-slot="slider-value"]')).toContainText("55");
  await expect(reference).toHaveCSS("opacity", "0.55");
  expect(actions).toEqual([]);
});

test("filters the view tree while retaining the selected control", async ({ page }) => {
  const actions: unknown[] = [];
  await mockInspectorApi(page, actions);
  await page.goto("/");

  const sidebar = page.getByRole("complementary");
  const hiddenToggle = sidebar.getByRole("button", { name: "Hidden", exact: true });
  const menuToggle = sidebar.getByRole("button", { name: "Menus", exact: true });
  const rootsToggle = sidebar.getByRole("button", { name: "Roots", exact: true });

  await expect(sidebar.getByText("View tree", { exact: true })).toHaveCount(0);
  await expect(sidebar.locator('[data-slot="toggle-group"]')).toHaveCount(1);

  await expect(sidebar.getByRole("button", { name: "Test widgets · LLFloater" })).toBeVisible();
  await expect(sidebar.getByRole("button", { name: "Save · LLButton" })).toBeVisible();
  await expect(sidebar.getByRole("button", { name: "Floater View · LLFloaterView" })).toHaveCount(
    0,
  );
  await expect(sidebar.getByRole("button", { name: "Menu Holder · LLMenuHolderGL" })).toHaveCount(
    0,
  );
  await expect(sidebar.getByRole("button", { name: "Hidden action · LLButton" })).toHaveCount(0);

  await hiddenToggle.click();
  const hiddenControl = sidebar.getByRole("button", { name: "Hidden action · LLButton" });
  await expect(hiddenControl).toBeVisible();
  await hiddenControl.click();
  await expect(hiddenControl).toHaveAttribute("aria-current", "true");
  await hiddenToggle.click();
  await expect(hiddenToggle).toHaveAttribute("aria-pressed", "false");
  await expect(hiddenControl).toBeVisible();
  await expect(hiddenControl).toBeInViewport();

  await menuToggle.click();
  await expect(sidebar.getByRole("button", { name: "Menu Holder · LLMenuHolderGL" })).toBeVisible();
  await rootsToggle.click();
  await expect(sidebar.getByRole("button", { name: "Floater View · LLFloaterView" })).toBeVisible();
});

test("uses a full-width toolbar and switches selections immediately", async ({ page }) => {
  const actions: unknown[] = [];
  await mockInspectorApi(page, actions, {
    state: {
      ...inspectorState,
      subject: "inventory_explorer",
      fixture: "inventory_explorer",
      subjects: ["inventory_explorer", "test_widgets"],
      fixtures: ["inventory_explorer", "empty_inventory"],
    },
  });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  const toolbar = page.getByRole("toolbar", { name: "Runtime controls" });
  await expect(toolbar.getByLabel("Subject")).toContainText("inventory_explorer");
  await expect(toolbar.getByLabel("Fixture")).toContainText("inventory_explorer");
  await expect(page.getByRole("button", { name: "Open" })).toHaveCount(0);

  const toolbarBox = await toolbar.boundingBox();
  expect(toolbarBox?.x).toBe(0);
  expect(toolbarBox?.width).toBe(1280);

  const replayBox = await toolbar.getByRole("button", { name: "Replay" }).boundingBox();
  const reloadBox = await toolbar.getByRole("button", { name: "Reload XUI" }).boundingBox();
  const exportBox = await toolbar.getByRole("button", { name: "Export Tree" }).boundingBox();
  expect(reloadBox?.x).toBeGreaterThan(replayBox?.x ?? Number.POSITIVE_INFINITY);
  expect(exportBox?.x).toBeGreaterThan(reloadBox?.x ?? Number.POSITIVE_INFINITY);

  await toolbar.getByLabel("Fixture").click();
  await page.getByRole("option", { name: "empty_inventory" }).click();
  await expect
    .poll(() => actions.at(-1))
    .toMatchObject({
      schemaVersion: 1,
      action: "switch",
      subject: "inventory_explorer",
      fixture: "empty_inventory",
    });

  await toolbar.getByLabel("Subject").click();
  await page.getByRole("option", { name: "test_widgets" }).click();
  await expect
    .poll(() => actions.at(-1))
    .toMatchObject({
      schemaVersion: 1,
      action: "switch",
      subject: "test_widgets",
      fixture: "",
    });
});

test("shows an error toast when an inspector action fails", async ({ page }) => {
  await mockInspectorApi(page, []);
  await page.route("**/api/v1/actions", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/problem+json",
      body: JSON.stringify({
        type: "about:blank",
        title: "Internal Server Error",
        status: 500,
        detail: "viewer died",
        schemaVersion: 1,
        code: "crash",
        operation: "capture",
        retryable: false,
      }),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Reload XUI" }).click();
  await expect(page.getByText("reload failed")).toBeVisible();
  await expect(page.getByText("viewer died (HTTP 500)")).toBeVisible();
});

test("names the rejected field when an action fails validation", async ({ page }) => {
  await mockInspectorApi(page, []);
  await page.route("**/api/v1/actions", async (route) => {
    await route.fulfill({
      status: 400,
      contentType: "application/problem+json",
      body: JSON.stringify({
        type: "https://xui-lab.local/problems/invalid_interactive_action",
        title: "Bad Request",
        status: 400,
        detail: "invalid interactive action: selector.path must match '^/'",
        details: ["selector.path must match '^/'"],
        schemaVersion: 1,
        code: "invalid_interactive_action",
        operation: "inspector.action",
        retryable: false,
      }),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Reload XUI" }).click();
  await expect(page.getByText("reload failed")).toBeVisible();
  await expect(page.getByText("selector.path must match '^/'")).toBeVisible();
});

test("scrubs a historical capture without sending a highlight action", async ({ page }) => {
  const actions: unknown[] = [];
  await mockInspectorApi(page, actions);
  await page.goto("/");
  const timeline = page.getByRole("slider", { name: "Capture timeline" });
  await expect(timeline).toBeVisible();
  await expect(page.getByText("800×600 · 1× · no fixture · Default")).toBeVisible();
  const box = await timeline.boundingBox();
  expect(box).not.toBeNull();
  if (box === null) {
    return;
  }
  await page.mouse.move(box.x + 4, box.y + box.height - 8);
  await expect(timeline.getByText("initial")).toBeVisible();
  await page.mouse.click(box.x + 4, box.y + box.height - 8);
  const inspect = page.getByRole("button", { name: "Inspect" });
  await inspect.click();
  await expect(inspect).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");
  await expect(inspect).toHaveAttribute("aria-pressed", "false");
  expect(actions).toEqual([]);
});

test("keeps a large screenshot inside the panel and the capture timeline on screen", async ({
  page,
}) => {
  const captures = Array.from({ length: 40 }, (_, index) => ({
    version: index + 1,
    sequence: index + 1,
    action: index === 0 ? "initial" : `clickAt-${String(index + 1)}`,
    name: `interactive-${String(index + 1).padStart(4, "0")}`,
    label: "800×600 · 1× · no fixture · Default",
  }));
  await mockInspectorApi(page, [], {
    capturePng: largePng,
    state: {
      ...inspectorState,
      capture: { available: true, version: captures.length },
      captures,
    },
  });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  const screenshot = page.getByRole("img", { name: "xui-lab screenshot" });
  const timeline = page.getByRole("slider", { name: "Capture timeline" });
  await expect(screenshot).toBeVisible();
  await expect(timeline).toBeVisible();
  await expect(timeline).toBeInViewport();
  await expect(screenshot).toBeInViewport();

  const panel = page.locator("#snapshotPanel");
  const panelBox = await panel.boundingBox();
  const imageBox = await screenshot.boundingBox();
  const timelineBox = await timeline.boundingBox();
  expect(panelBox).not.toBeNull();
  expect(imageBox).not.toBeNull();
  expect(timelineBox).not.toBeNull();
  if (panelBox === null || imageBox === null || timelineBox === null) {
    return;
  }
  expect(imageBox.width).toBeGreaterThan(100);
  expect(imageBox.width).toBeLessThanOrEqual(panelBox.width + 1);
  expect(imageBox.height).toBeLessThanOrEqual(panelBox.height + 1);
  expect(imageBox.x).toBeGreaterThanOrEqual(panelBox.x - 1);
  expect(imageBox.x + imageBox.width).toBeLessThanOrEqual(panelBox.x + panelBox.width + 1);
  expect(imageBox.y).toBeGreaterThanOrEqual(panelBox.y - 1);
  expect(timelineBox.y).toBeGreaterThan(imageBox.y);
  expect(timelineBox.y + timelineBox.height).toBeLessThanOrEqual(panelBox.y + panelBox.height + 1);

  await page.evaluate(
    async () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            resolve();
          });
        });
      }),
  );
  const laterBox = await screenshot.boundingBox();
  expect(laterBox?.width).toBe(imageBox.width);
  expect(laterBox?.height).toBe(imageBox.height);
  expect(laterBox?.x).toBe(imageBox.x);
});

test("resizes the view tree sidebar", async ({ page }) => {
  await mockInspectorApi(page, []);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  const sidebar = page.getByRole("complementary");
  const handle = page.locator('[data-slot="resizable-handle"]');
  await expect(handle).toBeVisible();
  const before = await sidebar.boundingBox();
  const handleBox = await handle.boundingBox();
  expect(before).not.toBeNull();
  expect(handleBox).not.toBeNull();
  if (before === null || handleBox === null) {
    return;
  }
  await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + 40);
  await page.mouse.down();
  await page.mouse.move(handleBox.x + 80, handleBox.y + 40);
  await page.mouse.up();
  const after = await sidebar.boundingBox();
  expect(after).not.toBeNull();
  if (after === null) {
    return;
  }
  expect(after.width).toBeGreaterThan(before.width + 40);
});

test("sends typed inspector actions through the generated client", async ({ page }) => {
  const actions: unknown[] = [];
  await mockInspectorApi(page, actions);
  await page.goto("/");
  await page.getByRole("button", { name: "Reload XUI" }).click();
  await expect.poll(() => actions.length).toBeGreaterThan(0);
  expect(actions[0]).toEqual(
    expect.objectContaining({ schemaVersion: 1, action: "reload", requestId: expect.any(String) }),
  );
  await page.getByRole("button", { name: "Save · LLButton" }).click();
  await expect.poll(() => actions.length).toBeGreaterThan(1);
  expect(actions[1]).toEqual(
    expect.objectContaining({
      schemaVersion: 1,
      action: "highlight",
      selector: { schemaVersion: 1, kind: "role", role: "button", name: "Save" },
    }),
  );
});
