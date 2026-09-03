import { describe, expect, it } from "vitest";
import { validateEvent, validateState } from "./generated/validators";
import validatorsSource from "./generated/validators.js?raw";

describe("generated OpenAPI validators", () => {
  it("does not evaluate JavaScript at runtime", () => {
    expect(validatorsSource).not.toContain("Function(");
    expect(validatorsSource).not.toContain("eval(");
    expect(validatorsSource).not.toContain("require(");
  });

  it("accepts a minimal inspector state document", () => {
    expect(
      validateState({
        tree: { control_id: "root", path: "/root", children: [] },
        diagnostics: {},
        recording: [],
        locators: {},
        artifactDir: "/tmp",
        subjects: [],
        fixtures: [],
        scenarios: [],
        inputOperations: [],
        capture: { available: false, version: 0 },
        stateVersion: 0,
        openapiHash: "abc",
      }),
    ).toBe(true);
  });

  it("rejects a session event missing required fields", () => {
    expect(validateEvent({})).toBe(false);
    expect(validateEvent.errors?.[0]?.message).toMatch(/required/i);
  });
});
