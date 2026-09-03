import Ajv, { type ValidateFunction } from "ajv";
import createClient from "openapi-fetch";
import openapiDocument from "../../schemas/inspector.openapi.json";
import {
  type InspectorAction,
  type InspectorSessionEvent,
  type InspectorState,
  parseActionResponse,
  parseInspectorSessionEvent,
  parseInspectorState,
} from "./contracts";
import type { components, paths } from "./generated/inspector-api";

type WireState = components["schemas"]["InspectorStateDocument"];
type WireActionResponse = components["schemas"]["InspectorActionAccepted"];
type ProblemDetails = components["schemas"]["InspectorProblemDetails"];

const ajv = new Ajv({ allErrors: true, strict: false });
const schemaRoot = { components: openapiDocument.components };
const validateState = ajv.compile<WireState>({
  ...schemaRoot,
  $ref: "#/components/schemas/InspectorStateDocument",
});
const validateActionResponse = ajv.compile<WireActionResponse>({
  ...schemaRoot,
  $ref: "#/components/schemas/InspectorActionAccepted",
});
const validateProblem = ajv.compile<ProblemDetails>({
  ...schemaRoot,
  $ref: "#/components/schemas/InspectorProblemDetails",
});
const validateEvent = ajv.compile<InspectorSessionEvent>(
  openapiDocument.paths["/api/v1/events"].get.responses["200"].content["text/event-stream"].schema,
);
const client = createClient<paths>({ baseUrl: "" });
const STATE_TIMEOUT_MS = 30_000;
const ACTION_TIMEOUT_MS = 120_000;

function requireValid<T>(validator: ValidateFunction<T>, value: unknown, context: string): T {
  if (!validator(value)) {
    throw new Error(`${context} violates the OpenAPI schema: ${ajv.errorsText(validator.errors)}`);
  }
  return value;
}

function problemError(value: unknown, response: Response): Error {
  const problem = requireValid(validateProblem, value, "API error");
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
  return parseInspectorState(requireValid(validateState, data, "Inspector state"));
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
  return parseActionResponse(requireValid(validateActionResponse, data, "Action response"));
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
        parseInspectorSessionEvent(requireValid(validateEvent, value, "Session event")),
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
