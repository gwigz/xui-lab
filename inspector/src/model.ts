import type { InspectorAction } from "./contracts";

export type InspectorTab = "snapshot" | "selected" | "focus" | "recording";

export type RunInspectorAction = (
  action: InspectorAction,
  nextTab?: InspectorTab,
) => Promise<unknown>;
