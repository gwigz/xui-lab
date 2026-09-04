export type SubjectSizePreset = Readonly<{
  id: string;
  label: string;
  width: number;
  height: number;
}>;

export const SUBJECT_SIZE_PRESETS: readonly SubjectSizePreset[] = [
  { id: "narrow", label: "Narrow", width: 360, height: 580 },
  { id: "reference", label: "Reference", width: 800, height: 640 },
  { id: "wide", label: "Wide", width: 1024, height: 700 },
];

export const UI_SCALE_PRESETS: readonly number[] = [1, 1.25];

export function viewportAtScale(
  width: number,
  height: number,
  currentScale: number,
  targetScale: number,
): Readonly<{ width: number; height: number; uiScale: number }> {
  return {
    width: Math.round((width / currentScale) * targetScale),
    height: Math.round((height / currentScale) * targetScale),
    uiScale: targetScale,
  };
}
