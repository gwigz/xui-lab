export const FILMSTRIP_TILE_AREA: Readonly<{ width: number; height: number }> = {
  width: 200,
  height: 45,
};
export const FILMSTRIP_FRAME_MARGIN = 2.5;

export function inscribe(
  object: Readonly<{ width: number; height: number }>,
  area: Readonly<{ width: number; height: number }>,
): { width: number; height: number } {
  const scale = Math.max(object.width / area.width, object.height / area.height, Number.EPSILON);
  return {
    width: Math.max(1, (object.width / scale) | 0),
    height: Math.max(1, (object.height / scale) | 0),
  };
}

export function captureIndexAt(x: number, width: number, count: number): number {
  if (count <= 0 || width <= 0) {
    return 0;
  }
  const t = Math.min(1, Math.max(0, x / width));
  return Math.min(count - 1, Math.floor(t * count));
}

export function filmstripTiles(
  captureCount: number,
  width: number,
  frameWidth: number,
  margin: number,
): readonly number[] {
  if (captureCount <= 0 || width <= 0 || frameWidth <= 0) {
    return [];
  }
  const frameCount = Math.max(1, Math.floor(width / (frameWidth + 2 * margin)));
  const tiles: number[] = [];
  for (let i = 0; i < frameCount; i += 1) {
    tiles.push(
      frameCount === 1
        ? captureCount - 1
        : Math.min(captureCount - 1, Math.floor((i / frameCount) * captureCount)),
    );
  }
  tiles[tiles.length - 1] = captureCount - 1;
  return tiles;
}

export function playheadPercent(index: number, count: number): number {
  if (count <= 0) {
    return 0;
  }
  return ((Math.min(Math.max(index, 0), count - 1) + 0.5) / count) * 100;
}
