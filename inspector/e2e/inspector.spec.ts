import { expect, type Page, test } from "@playwright/test";
import { OPENAPI_HASH } from "../src/generated/openapi-hash";

const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

const inspectorState = {
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
  diagnostics: {
    processId: 42,
    viewport: { lluiWidth: 800, lluiHeight: 600, windowWidth: 800, windowHeight: 600, uiScale: 1 },
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
  subjects: ["test_widgets"],
  fixtures: [],
  scenarios: ["test_floater"],
  inputOperations: ["click", "drag", "fill"],
  capture: { available: true, version: 2 },
  stateVersion: 4,
  openapiHash: OPENAPI_HASH,
};

async function mockInspectorApi(page: Page, actions: unknown[]): Promise<void> {
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
      body: JSON.stringify(inspectorState),
    });
  });
  await page.route("**/api/v1/captures/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/png", body: png });
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
  const actions: unknown[] = [];
  await mockInspectorApi(page, actions);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Save · LLButton" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Latest xui-lab screenshot" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("/tmp/artifacts");
});

test("sends typed inspector actions through the generated client", async ({ page }) => {
  const actions: unknown[] = [];
  await mockInspectorApi(page, actions);
  await page.goto("/");
  await page.getByRole("button", { name: "Screenshot" }).click();
  await expect.poll(() => actions.length).toBeGreaterThan(0);
  expect(actions[0]).toEqual(
    expect.objectContaining({ schemaVersion: 1, action: "capture", requestId: expect.any(String) }),
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
