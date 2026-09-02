export type FramePoint = Readonly<{ x: number; y: number }>;

export function framePoint(
  clientX: number,
  clientY: number,
  bounds: Readonly<{ left: number; top: number; width: number; height: number }>,
  lluiWidth: number,
  lluiHeight: number,
): FramePoint {
  if (bounds.width <= 0 || bounds.height <= 0 || lluiWidth <= 0 || lluiHeight <= 0) {
    throw new Error("captured frame geometry must be positive");
  }

  const imageX = Math.min(Math.max(clientX - bounds.left, 0), bounds.width);
  const imageY = Math.min(Math.max(clientY - bounds.top, 0), bounds.height);

  return {
    x: Math.round((imageX / bounds.width) * lluiWidth),
    y: Math.round((1 - imageY / bounds.height) * lluiHeight),
  };
}
