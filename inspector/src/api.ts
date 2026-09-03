import createClient from "openapi-fetch";
import {
  type CaptureSnapshot,
  type InspectorAction,
  type InspectorSessionEvent,
  type InspectorState,
  parseActionResponse,
  parseCaptureSnapshot,
  parseInspectorSessionEvent,
  parseInspectorState,
} from "./contracts";
import type { components, paths } from "./generated/inspector-api";
import {
  type OpenApiValidator,
  validateActionResponse,
  validateEvent,
  validateProblem,
  validateSnapshot,
  validateState,
} from "./generated/validators";

type WireState = components["schemas"]["InspectorStateDocument"];
type WireActionResponse = components["schemas"]["InspectorActionAccepted"];
type WireSnapshot = components["schemas"]["InspectorCaptureSnapshot"];
type ProblemDetails = components["schemas"]["InspectorProblemDetails"];

const client = createClient<paths>({ baseUrl: "" });
const STATE_TIMEOUT_MS = 30_000;
const ACTION_TIMEOUT_MS = 120_000;

function schemaErrorsText(errors: OpenApiValidator["errors"]): string {
  if (errors == null || errors.length === 0) {
    return "unknown error";
  }
  return errors
    .map((error) => {
      const path =
        error.instancePath === undefined || error.instancePath === "" ? "/" : error.instancePath;
      return `${path} ${error.message ?? "is invalid"}`;
    })
    .join(", ");
}

function requireValid<T>(validator: OpenApiValidator, value: unknown, context: string): T {
  if (!validator(value)) {
    throw new Error(
      `${context} violates the OpenAPI schema: ${schemaErrorsText(validator.errors)}`,
    );
  }
  return value as T;
}

function problemError(value: unknown, response: Response): Error {
  const problem = requireValid<ProblemDetails>(validateProblem, value, "API error");
  return new Error(`${problem.code}: ${problem.detail} (${response.status})`);
}

export async function fetchInspectorState(signal?: AbortSignal): Promise<InspectorState> {
  const timeout = AbortSignal.timeout(STATE_TIMEOUT_MS);
  const requestSignal = signal === undefined ? timeout : AbortSignal.any([signal, timeout]);
  const { data, error, response } = await client.GET("/api/v1/state", {
    signal: requestSignal,
  });
  if (error !== undefined) {
    throw problemError(error, response);
  }
  return parseInspectorState(requireValid<WireState>(validateState, data, "Inspector state"));
}

export async function fetchCaptureSnapshot(version: number): Promise<CaptureSnapshot> {
  const { data, error, response } = await client.GET("/api/v1/captures/{version}/snapshot", {
    params: { path: { version } },
    signal: AbortSignal.timeout(STATE_TIMEOUT_MS),
  });
  if (error !== undefined) {
    throw problemError(error, response);
  }
  return parseCaptureSnapshot(
    requireValid<WireSnapshot>(validateSnapshot, data, "Capture snapshot"),
  );
}

export async function performAction(action: InspectorAction): Promise<unknown> {
  const request = {
    ...action,
    requestId: crypto.randomUUID(),
  };
  const { data, error, response } = await client.POST("/api/v1/actions", {
    body: request,
    signal: AbortSignal.timeout(ACTION_TIMEOUT_MS),
  });
  if (error !== undefined) {
    throw problemError(error, response);
  }
  return parseActionResponse(
    requireValid<WireActionResponse>(validateActionResponse, data, "Action response"),
  );
}

export function subscribeInspectorEvents(
  onEvent: (event: InspectorSessionEvent, reset: boolean) => void,
  onError?: (source: EventSource) => void,
): () => void {
  const source = new EventSource("/api/v1/events");
  let closed = false;

  const handleStateEvent = (message: Event, reset: boolean) => {
    if (!(message instanceof MessageEvent) || typeof message.data !== "string") {
      return;
    }

    try {
      const value: unknown = JSON.parse(message.data);
      onEvent(
        parseInspectorSessionEvent(
          requireValid<InspectorSessionEvent>(validateEvent, value, "Session event"),
        ),
        reset,
      );
    } catch {
      return;
    }
  };

  source.addEventListener("invalidate", (message) => handleStateEvent(message, false));
  source.addEventListener("reset", (message) => handleStateEvent(message, true));

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
