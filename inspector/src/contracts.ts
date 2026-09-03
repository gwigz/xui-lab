export type TreeNode = Readonly<{
  children: readonly TreeNode[];
  controlId: string;
  path: string;
  title: string;
  raw: Readonly<Record<string, unknown>>;
}>;

export type FrameRect = Readonly<{
  left: number;
  right: number;
  bottom: number;
  top: number;
}>;

export type CaptureState =
  | Readonly<{ kind: "empty"; version: number }>
  | Readonly<{ kind: "available"; version: number }>;

export type RankedLocator = Readonly<{
  selector: Selector;
  python: string;
  kind: string;
  matchCount: number;
  signals: readonly string[];
  fallbackReason: string | null;
}>;

export type KeyboardModifier = "shift" | "control" | "alt";

export type Selector =
  | Readonly<{ schemaVersion: 1; kind: "role"; role: string; name?: string }>
  | Readonly<{ schemaVersion: 1; kind: "label"; label: string }>
  | Readonly<{ schemaVersion: 1; kind: "placeholder"; placeholder: string }>
  | Readonly<{ schemaVersion: 1; kind: "text"; text: string }>
  | Readonly<{ schemaVersion: 1; kind: "modelId"; modelId: string }>
  | Readonly<{ schemaVersion: 1; kind: "controlId"; controlId: string }>
  | Readonly<{ schemaVersion: 1; kind: "path"; path: string }>;

export function controlIdSelector(controlId: string): Selector {
  return { schemaVersion: 1, kind: "controlId", controlId };
}

export function modelIdSelector(modelId: string): Selector {
  return { schemaVersion: 1, kind: "modelId", modelId };
}

export type InspectorState = Readonly<{
  tree: TreeNode;
  diagnostics: Readonly<Record<string, unknown>>;
  recording: readonly string[];
  locators: Readonly<Record<string, RankedLocator>>;
  artifactDir: string;
  subjects: readonly string[];
  fixtures: readonly string[];
  scenarios: readonly string[];
  inputOperations: readonly string[];
  capture: CaptureState;
}>;

export type InspectorAction =
  | Readonly<{ action: "reload" }>
  | Readonly<{ action: "highlight"; selector: Selector }>
  | Readonly<{ action: "pick"; x: number; y: number }>
  | Readonly<{ action: "resizeViewport"; width: number; height: number; uiScale: number }>
  | Readonly<{ action: "resizeSubject"; width: number; height: number }>
  | Readonly<{ action: "capture" }>
  | Readonly<{ action: "export" }>
  | Readonly<{ action: "click"; selector: Selector }>
  | Readonly<{ action: "clickAt"; x: number; y: number }>
  | Readonly<{ action: "doubleClickAt"; x: number; y: number }>
  | Readonly<{ action: "rightClickAt"; x: number; y: number }>
  | Readonly<{
      action: "drag";
      startX: number;
      startY: number;
      endX: number;
      endY: number;
    }>
  | Readonly<{ action: "scrollAt"; x: number; y: number; clicks: number }>
  | Readonly<{
      action: "dragAndDrop";
      source: Selector;
      target: Selector;
    }>
  | Readonly<{ action: "fill"; selector: Selector; text: string }>
  | Readonly<{ action: "type"; selector: Selector; text: string }>
  | Readonly<{
      action: "press";
      selector: Selector;
      key: string;
      modifiers?: readonly KeyboardModifier[];
    }>
  | Readonly<{ action: "replay"; scenario: string }>
  | Readonly<{ action: "switch"; subject: string; fixture: string }>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function objectValue(value: unknown, context: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`${context} must be an object`);
  }

  return value;
}

function stringValue(value: unknown, context: string): string {
  if (typeof value !== "string") {
    throw new Error(`${context} must be a string`);
  }

  return value;
}

function nonEmptyStringValue(value: unknown, context: string): string {
  const parsed = stringValue(value, context);
  if (parsed.length === 0) {
    throw new Error(`${context} must be non-empty`);
  }
  return parsed;
}

function numberValue(value: unknown, context: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${context} must be a finite number`);
  }

  return value;
}

function booleanValue(value: unknown, context: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${context} must be a boolean`);
  }

  return value;
}

function stringArray(value: unknown, context: string): readonly string[] {
  if (!Array.isArray(value)) {
    throw new Error(`${context} must be an array`);
  }

  return value.map((entry, index) => stringValue(entry, `${context}[${index}]`));
}

function optionalString(record: Record<string, unknown>, key: string): string | undefined {
  const value = record[key];

  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function parseRankedLocator(value: unknown, context: string): RankedLocator {
  const record = objectValue(value, context);
  const fallbackReason = record.fallbackReason;
  if (fallbackReason !== null && typeof fallbackReason !== "string") {
    throw new Error(`${context}.fallbackReason must be a string or null`);
  }
  return {
    selector: parseSelector(record.selector, `${context}.selector`),
    python: stringValue(record.python, `${context}.python`),
    kind: stringValue(record.kind, `${context}.kind`),
    matchCount: numberValue(record.matchCount, `${context}.matchCount`),
    signals: stringArray(record.signals, `${context}.signals`),
    fallbackReason,
  };
}

function parseSelector(value: unknown, context: string): Selector {
  const record = objectValue(value, context);
  if (record.schemaVersion !== 1) {
    throw new Error(`${context}.schemaVersion must be 1`);
  }
  const kind = stringValue(record.kind, `${context}.kind`);
  if (kind === "role") {
    const name = record.name;
    if (name !== undefined && typeof name !== "string") {
      throw new Error(`${context}.name must be a string`);
    }
    return {
      schemaVersion: 1,
      kind,
      role: nonEmptyStringValue(record.role, `${context}.role`),
      name: name === undefined ? undefined : nonEmptyStringValue(name, `${context}.name`),
    };
  }
  if (kind === "label") {
    return {
      schemaVersion: 1,
      kind,
      label: nonEmptyStringValue(record.label, `${context}.label`),
    };
  }
  if (kind === "placeholder") {
    return {
      schemaVersion: 1,
      kind,
      placeholder: nonEmptyStringValue(record.placeholder, `${context}.placeholder`),
    };
  }
  if (kind === "text") {
    return {
      schemaVersion: 1,
      kind,
      text: nonEmptyStringValue(record.text, `${context}.text`),
    };
  }
  if (kind === "modelId") {
    const modelId = nonEmptyStringValue(record.modelId, `${context}.modelId`);
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(modelId)) {
      throw new Error(`${context}.modelId must be a UUID string`);
    }
    return { schemaVersion: 1, kind, modelId };
  }
  if (kind === "controlId") {
    return {
      schemaVersion: 1,
      kind,
      controlId: nonEmptyStringValue(record.controlId, `${context}.controlId`),
    };
  }
  if (kind === "path") {
    const path = nonEmptyStringValue(record.path, `${context}.path`);
    if (!path.startsWith("/")) {
      throw new Error(`${context}.path must be an absolute XUI path`);
    }
    return { schemaVersion: 1, kind, path };
  }
  throw new Error(`${context}.kind is not supported`);
}

function parseRankedLocators(value: unknown): Readonly<Record<string, RankedLocator>> {
  const record = objectValue(value, "state.locators");
  return Object.fromEntries(
    Object.entries(record).map(([controlId, locator]) => [
      controlId,
      parseRankedLocator(locator, `state.locators.${controlId}`),
    ]),
  );
}

function parseTreeNode(value: unknown, context = "state.tree"): TreeNode {
  const record = objectValue(value, context);
  const controlId = stringValue(record.control_id, `${context}.control_id`);
  const path = stringValue(record.path, `${context}.path`);
  const childValues = record.children;

  if (!Array.isArray(childValues)) {
    throw new Error(`${context}.children must be an array`);
  }

  const runtimeClass = optionalString(record, "class")?.replace(/^\d+/, "");
  const semantic = optionalString(record, "label") ?? optionalString(record, "name");
  const title =
    semantic !== undefined && runtimeClass !== undefined && semantic !== runtimeClass
      ? `${semantic} · ${runtimeClass}`
      : (semantic ?? runtimeClass ?? path);

  return {
    controlId,
    path,
    title,
    children: childValues.map((child, index) =>
      parseTreeNode(child, `${context}.children[${index}]`),
    ),
    raw: record,
  };
}

export function parseInspectorState(value: unknown): InspectorState {
  const record = objectValue(value, "state");
  const capture = objectValue(record.capture, "state.capture");
  const available = booleanValue(capture.available, "state.capture.available");
  const version = numberValue(capture.version, "state.capture.version");

  return {
    tree: parseTreeNode(record.tree),
    diagnostics: objectValue(record.diagnostics, "state.diagnostics"),
    recording: stringArray(record.recording, "state.recording"),
    locators: parseRankedLocators(record.locators),
    artifactDir: stringValue(record.artifactDir, "state.artifactDir"),
    subjects: stringArray(record.subjects, "state.subjects"),
    fixtures: stringArray(record.fixtures, "state.fixtures"),
    scenarios: stringArray(record.scenarios, "state.scenarios"),
    inputOperations: stringArray(record.inputOperations, "state.inputOperations"),
    capture: available ? { kind: "available", version } : { kind: "empty", version },
  };
}

export function parseActionResponse(value: unknown): unknown {
  const record = objectValue(value, "action response");
  const ok = booleanValue(record.ok, "action response.ok");

  if (!ok) {
    const error = objectValue(record.error, "action response.error");
    const code = stringValue(error.code, "action response.error.code");
    const message = stringValue(error.message, "action response.error.message");
    throw new Error(`${code}: ${message}`);
  }

  return record.result;
}

export function reviewableLocatorPython(locator: RankedLocator): string {
  const fallback = locator.fallbackReason ?? "none";
  const explanation = `# locator: signals=${locator.signals.join(", ")}; matches=${locator.matchCount}; fallback=${fallback}`;
  return `${explanation}\n${locator.python}`;
}

export function recordValue(value: unknown): Readonly<Record<string, unknown>> | undefined {
  return isRecord(value) ? value : undefined;
}

export function findTreeNode(node: TreeNode, path: string): TreeNode | undefined {
  if (node.path === path) {
    return node;
  }

  for (const child of node.children) {
    const found = findTreeNode(child, path);

    if (found !== undefined) {
      return found;
    }
  }

  return undefined;
}

export function findTreeNodeByControlId(node: TreeNode, controlId: string): TreeNode | undefined {
  if (node.controlId === controlId) {
    return node;
  }

  for (const child of node.children) {
    const found = findTreeNodeByControlId(child, controlId);

    if (found !== undefined) {
      return found;
    }
  }

  return undefined;
}

function frameRect(value: unknown): FrameRect | undefined {
  const record = recordValue(value);
  const left = record?.left;
  const right = record?.right;
  const bottom = record?.bottom;
  const top = record?.top;

  if (
    typeof left !== "number" ||
    !Number.isFinite(left) ||
    typeof right !== "number" ||
    !Number.isFinite(right) ||
    typeof bottom !== "number" ||
    !Number.isFinite(bottom) ||
    typeof top !== "number" ||
    !Number.isFinite(top)
  ) {
    return undefined;
  }

  return { left, right, bottom, top };
}

export function treeNodeVisibleRect(node: TreeNode): FrameRect | undefined {
  if (node.raw.visible_chain !== true) {
    return undefined;
  }

  const screen = frameRect(node.raw.screen_rect);
  if (screen === undefined) {
    return undefined;
  }

  const clipping = frameRect(node.raw.clipping_rect) ?? screen;
  const visible = {
    left: Math.max(screen.left, clipping.left),
    right: Math.min(screen.right, clipping.right),
    bottom: Math.max(screen.bottom, clipping.bottom),
    top: Math.min(screen.top, clipping.top),
  };

  return visible.right > visible.left && visible.top > visible.bottom ? visible : undefined;
}

function findTreeNodeAtPointWhere(
  node: TreeNode,
  point: Readonly<{ x: number; y: number }>,
  accepts: (candidate: TreeNode) => boolean,
): TreeNode | undefined {
  let best: Readonly<{ node: TreeNode; area: number; depth: number }> | undefined;

  function visit(candidate: TreeNode, depth: number): void {
    if (candidate.raw.visible_chain !== true) {
      return;
    }

    const rect = treeNodeVisibleRect(candidate);
    if (
      rect !== undefined &&
      point.x >= rect.left &&
      point.x <= rect.right &&
      point.y >= rect.bottom &&
      point.y <= rect.top
    ) {
      const area = (rect.right - rect.left) * (rect.top - rect.bottom);
      if (
        accepts(candidate) &&
        (best === undefined || area < best.area || (area === best.area && depth > best.depth))
      ) {
        best = { node: candidate, area, depth };
      }
    }

    for (const child of candidate.children) {
      visit(child, depth + 1);
    }
  }

  visit(node, 0);
  return best?.node;
}

export function findTreeNodeAtPoint(
  node: TreeNode,
  point: Readonly<{ x: number; y: number }>,
): TreeNode | undefined {
  return findTreeNodeAtPointWhere(node, point, () => true);
}

export function findModelTreeNodeAtPoint(
  node: TreeNode,
  point: Readonly<{ x: number; y: number }>,
): TreeNode | undefined {
  return findTreeNodeAtPointWhere(
    node,
    point,
    (candidate) => typeof candidate.raw.model_id === "string" && candidate.raw.model_id.length > 0,
  );
}
