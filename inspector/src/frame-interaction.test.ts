import { describe, expect, it } from "vitest";
import { browserKeyPress, frameOutline, framePoint } from "./frame-interaction";

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

describe("browserKeyPress", () => {
  it("translates browser key names and preserves supported modifiers", () => {
    expect(
      browserKeyPress({
        key: "ArrowLeft",
        shiftKey: true,
        ctrlKey: true,
        altKey: false,
        metaKey: false,
        isComposing: false,
      }),
    ).toEqual({ key: "Left", modifiers: ["shift", "control"] });
    expect(
      browserKeyPress({
        key: "Backspace",
        shiftKey: false,
        ctrlKey: false,
        altKey: false,
        metaKey: false,
        isComposing: false,
      }),
    ).toEqual({ key: "Backsp", modifiers: [] });
  });

  it("leaves browser and composition-only keys in the browser", () => {
    expect(
      browserKeyPress({
        key: "Meta",
        shiftKey: false,
        ctrlKey: false,
        altKey: false,
        metaKey: true,
        isComposing: false,
      }),
    ).toBeUndefined();
    expect(
      browserKeyPress({
        key: "Dead",
        shiftKey: false,
        ctrlKey: false,
        altKey: false,
        metaKey: false,
        isComposing: true,
      }),
    ).toBeUndefined();
  });
});

describe("frameOutline", () => {
  it("projects a bottom-origin LLUI rectangle over the browser image", () => {
    expect(
      frameOutline(
        { left: 200, right: 600, bottom: 100, top: 300 },
        { left: 110, top: 70, width: 400, height: 200 },
        { left: 10, top: 20 },
        800,
        400,
      ),
    ).toEqual({ left: 200, top: 100, width: 200, height: 100 });
  });
});
