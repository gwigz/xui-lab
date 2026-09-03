import { describe, expect, it } from "vitest";
import { captureIndexAt, filmstripTiles, inscribe, playheadPercent } from "./filmstrip-geometry";

describe("inscribe", () => {
  it("fits a wide screenshot into the Playwright tile area", () => {
    expect(inscribe({ width: 2048, height: 1400 }, { width: 200, height: 45 })).toEqual({
      width: 65,
      height: 45,
    });
  });
});

describe("captureIndexAt", () => {
  it("maps the left edge to the first capture and the right edge to the last", () => {
    expect(captureIndexAt(0, 200, 10)).toBe(0);
    expect(captureIndexAt(199, 200, 10)).toBe(9);
    expect(captureIndexAt(-20, 200, 10)).toBe(0);
    expect(captureIndexAt(400, 200, 10)).toBe(9);
  });
});

describe("filmstripTiles", () => {
  it("samples captures across the available width and always ends on the last frame", () => {
    expect(filmstripTiles(40, 350, 65, 2.5)).toEqual([0, 8, 16, 24, 39]);
  });

  it("repeats frames when there are fewer captures than tiles", () => {
    expect(filmstripTiles(2, 280, 65, 2.5)).toEqual([0, 0, 1, 1]);
  });
});

describe("playheadPercent", () => {
  it("centers the playhead in the selected capture slot", () => {
    expect(playheadPercent(0, 4)).toBe(12.5);
    expect(playheadPercent(3, 4)).toBe(87.5);
  });
});
