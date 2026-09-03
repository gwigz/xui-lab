import {
  type InspectorAction,
  type InspectorSessionEvent,
  type InspectorState,
  parseActionResponse,
  parseInspectorSessionEvent,
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
  const response = await fetch("/api/v1/state", { signal });

  return parseInspectorState(await responseValue(response));
}

export async function performAction(action: InspectorAction): Promise<unknown> {
  const response = await fetch("/api/v1/actions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(action),
  });

  return parseActionResponse(await responseValue(response));
}

export function subscribeInspectorEvents(
  onEvent: (event: InspectorSessionEvent) => void,
  onError?: (source: EventSource) => void,
): () => void {
  const source = new EventSource("/api/v1/events");
  let closed = false;

  source.addEventListener("invalidate", (message: Event) => {
    if (!(message instanceof MessageEvent) || typeof message.data !== "string") {
      return;
    }

    try {
      onEvent(parseInspectorSessionEvent(JSON.parse(message.data) as unknown));
    } catch {
      return;
    }
  });

  source.onerror = () => {
    if (!closed) {
      onError?.(source);
    }
  };

  return () => {
    closed = true;
    source.close();
  };
}
