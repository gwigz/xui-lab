import { describe, expect, it } from "vitest";
import { framePoint } from "./frame-interaction";

describe("framePoint", () => {
  it("maps browser pixels into bottom-origin LLUI coordinates", () => {
    expect(framePoint(210, 120, { left: 10, top: 20, width: 400, height: 200 }, 800, 400)).toEqual({
      x: 400,
      y: 200,
    });
  });

  it("clamps pointer coordinates to the captured frame", () => {
    expect(framePoint(-20, 300, { left: 10, top: 20, width: 400, height: 200 }, 800, 400)).toEqual({
      x: 0,
      y: 0,
    });
  });
});
