import {
  type InspectorAction,
  type InspectorState,
  parseActionResponse,
  parseInspectorState,
} from "./contracts";

async function responseValue(response: Response): Promise<unknown> {
  const value: unknown = await response.json();

  if (!response.ok) {
    if (typeof value === "object" && value !== null && "error" in value) {
      const error = value.error;

      if (typeof error === "string") {
        throw new Error(error);
      }
    }

    throw new Error(`${response.status} ${response.statusText}`);
  }

  return value;
}

export async function fetchInspectorState(signal?: AbortSignal): Promise<InspectorState> {
  const response = await fetch("/api/state", { signal });

  return parseInspectorState(await responseValue(response));
}

export async function performAction(action: InspectorAction): Promise<unknown> {
  const response = await fetch("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(action),
  });

  return parseActionResponse(await responseValue(response));
}
