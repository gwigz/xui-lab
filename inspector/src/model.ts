import type { InspectorAction } from "./contracts";

export type InspectorTab = "snapshot" | "selected" | "focus" | "recording";

export type InspectorStatus = Readonly<{
  kind: "loading" | "ready" | "busy" | "error";
  message: string;
}>;

export type RunInspectorAction = (
  action: InspectorAction,
  nextTab?: InspectorTab,
) => Promise<unknown>;
