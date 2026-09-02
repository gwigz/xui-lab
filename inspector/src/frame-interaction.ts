import type { KeyboardModifier } from "./contracts";

export type FramePoint = Readonly<{ x: number; y: number }>;

export type FrameDragInput =
  | Readonly<{
      action: "drag";
      startX: number;
      startY: number;
      endX: number;
      endY: number;
    }>
  | Readonly<{
      action: "dragAndDrop";
      sourceControlId: string;
      targetControlId: string;
    }>;

export type BrowserFrameInput =
  | Readonly<{ action: "type"; text: string }>
  | Readonly<{
      action: "press";
      key: string;
      modifiers: readonly KeyboardModifier[];
    }>;

export type FrameOutline = Readonly<{
  left: number;
  top: number;
  width: number;
  height: number;
}>;

const browserKeyNames: Readonly<Record<string, string>> = {
  ArrowDown: "Down",
  ArrowLeft: "Left",
  ArrowRight: "Right",
  ArrowUp: "Up",
  Backspace: "Backsp",
  Delete: "Del",
  Escape: "Esc",
  Insert: "Ins",
  PageDown: "PgDn",
  PageUp: "PgUp",
  " ": "Space",
};

const browserOnlyKeys = new Set([
  "Alt",
  "Control",
  "Dead",
  "Meta",
  "Process",
  "Shift",
  "Unidentified",
]);

export function browserFrameInput(
  event: Readonly<{
    key: string;
    shiftKey: boolean;
    ctrlKey: boolean;
    altKey: boolean;
    metaKey: boolean;
    isComposing: boolean;
  }>,
): BrowserFrameInput | undefined {
  if (event.isComposing || event.key.length === 0 || browserOnlyKeys.has(event.key)) {
    return undefined;
  }

  if (Array.from(event.key).length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
    return { action: "type", text: event.key };
  }

  const modifiers: KeyboardModifier[] = [];
  if (event.shiftKey) {
    modifiers.push("shift");
  }
  if (event.ctrlKey || event.metaKey) {
    modifiers.push("control");
  }
  if (event.altKey) {
    modifiers.push("alt");
  }

  return {
    action: "press",
    key: browserKeyNames[event.key] ?? event.key,
    modifiers,
  };
}

export function framePoint(
  clientX: number,
  clientY: number,
  bounds: Readonly<{ left: number; top: number; width: number; height: number }>,
  lluiWidth: number,
  lluiHeight: number,
): FramePoint {
  if (bounds.width <= 0 || bounds.height <= 0 || lluiWidth <= 0 || lluiHeight <= 0) {
    throw new Error("captured frame geometry must be positive");
  }

  const imageX = Math.min(Math.max(clientX - bounds.left, 0), bounds.width);
  const imageY = Math.min(Math.max(clientY - bounds.top, 0), bounds.height);

  return {
    x: Math.round((imageX / bounds.width) * lluiWidth),
    y: Math.round((1 - imageY / bounds.height) * lluiHeight),
  };
}

export function wheelClicks(deltaY: number): number {
  return Math.sign(deltaY);
}

export function frameDragInput(
  input: Readonly<{
    start: FramePoint;
    end: FramePoint;
    sourceControlId?: string;
    sourceModelId?: string;
    targetControlId?: string;
    supportsDragAndDrop: boolean;
  }>,
): FrameDragInput {
  if (
    input.supportsDragAndDrop &&
    input.sourceModelId !== undefined &&
    input.sourceControlId !== undefined &&
    input.targetControlId !== undefined
  ) {
    return {
      action: "dragAndDrop",
      sourceControlId: input.sourceControlId,
      targetControlId: input.targetControlId,
    };
  }

  return {
    action: "drag",
    startX: input.start.x,
    startY: input.start.y,
    endX: input.end.x,
    endY: input.end.y,
  };
}

export function frameOutline(
  rect: Readonly<{ left: number; right: number; bottom: number; top: number }>,
  imageBounds: Readonly<{ left: number; top: number; width: number; height: number }>,
  containerBounds: Readonly<{ left: number; top: number }>,
  lluiWidth: number,
  lluiHeight: number,
): FrameOutline {
  if (imageBounds.width <= 0 || imageBounds.height <= 0 || lluiWidth <= 0 || lluiHeight <= 0) {
    throw new Error("captured frame geometry must be positive");
  }

  const left = Math.min(Math.max(rect.left, 0), lluiWidth);
  const right = Math.min(Math.max(rect.right, left), lluiWidth);
  const bottom = Math.min(Math.max(rect.bottom, 0), lluiHeight);
  const top = Math.min(Math.max(rect.top, bottom), lluiHeight);
  const scaleX = imageBounds.width / lluiWidth;
  const scaleY = imageBounds.height / lluiHeight;

  return {
    left: imageBounds.left - containerBounds.left + left * scaleX,
    top: imageBounds.top - containerBounds.top + (lluiHeight - top) * scaleY,
    width: (right - left) * scaleX,
    height: (top - bottom) * scaleY,
  };
}
