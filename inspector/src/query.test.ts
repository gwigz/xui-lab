import { describe, expect, it } from "vitest";
import { shouldInvalidateInspectorState } from "./query";

describe("shouldInvalidateInspectorState", () => {
  it("invalidates for newer state versions", () => {
    expect(shouldInvalidateInspectorState(4, 5, false)).toBe(true);
    expect(shouldInvalidateInspectorState(5, 4, false)).toBe(false);
  });

  it("forces a full refresh after an expired replay cursor", () => {
    expect(shouldInvalidateInspectorState(5, 5, true)).toBe(true);
  });
});
