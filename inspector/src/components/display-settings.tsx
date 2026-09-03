import { Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  NumberField,
  NumberFieldDecrement,
  NumberFieldGroup,
  NumberFieldIncrement,
  NumberFieldInput,
} from "@/components/ui/number-field";
import { Popover, PopoverPopup, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { type InspectorState, recordValue } from "../contracts";
import type { RunInspectorAction } from "../model";

function integer(value: number | null): number | undefined {
  return value !== null && Number.isInteger(value) ? value : undefined;
}

function finiteNumber(value: number | null): number | undefined {
  return value !== null && Number.isFinite(value) ? value : undefined;
}

type DisplaySettingsProps = Readonly<{
  state: InspectorState | null;
  runAction: RunInspectorAction;
}>;

export function DisplaySettings({ state, runAction }: DisplaySettingsProps) {
  const [viewportWidth, setViewportWidth] = useState<number | null>(800);
  const [viewportHeight, setViewportHeight] = useState<number | null>(600);
  const [scale, setScale] = useState<number | null>(1);
  const [viewportDirty, setViewportDirty] = useState(false);
  const [subjectWidth, setSubjectWidth] = useState<number | null>(null);
  const [subjectHeight, setSubjectHeight] = useState<number | null>(null);
  const [subjectDirty, setSubjectDirty] = useState(false);

  useEffect(() => {
    if (state === null || viewportDirty) {
      return;
    }
    const viewport = recordValue(state.diagnostics.viewport);
    if (typeof viewport?.windowWidth === "number") {
      setViewportWidth(viewport.windowWidth);
    }
    if (typeof viewport?.windowHeight === "number") {
      setViewportHeight(viewport.windowHeight);
    }
    if (typeof viewport?.uiScale === "number") {
      setScale(viewport.uiScale);
    }
  }, [state, viewportDirty]);

  useEffect(() => {
    if (state === null || subjectDirty) {
      return;
    }
    const subject = recordValue(state.diagnostics.subject);
    const view = recordValue(subject?.view);
    const rect = recordValue(view?.screen_rect);
    if (
      typeof rect?.left === "number" &&
      typeof rect.right === "number" &&
      typeof rect.bottom === "number" &&
      typeof rect.top === "number"
    ) {
      setSubjectWidth(rect.right - rect.left);
      setSubjectHeight(rect.top - rect.bottom);
    }
  }, [state, subjectDirty]);

  const canResize =
    integer(viewportWidth) !== undefined &&
    integer(viewportHeight) !== undefined &&
    finiteNumber(scale) !== undefined;
  const canResizeSubject =
    integer(subjectWidth) !== undefined && integer(subjectHeight) !== undefined;

  return (
    <Popover>
      <PopoverTrigger render={<Button size="xs" variant="outline" />}>
        <Settings2 aria-hidden size={14} />
        Settings
      </PopoverTrigger>
      <PopoverPopup align="end" className="w-76" side="bottom">
        <PopoverTitle className="text-sm">Display</PopoverTitle>
        <div className="mt-4 grid gap-4">
          <fieldset className="grid gap-2">
            <legend className="font-medium text-[11px] text-muted-foreground uppercase tracking-[0.08em]">
              Viewport
            </legend>
            <div className="grid gap-1.5">
              <NumberField
                className="grid grid-cols-[3rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1"
                format={{ useGrouping: false }}
                id="viewportWidth"
                largeStep={100}
                min={1}
                onValueChange={(value) => {
                  setViewportDirty(true);
                  setViewportWidth(value);
                }}
                size="sm"
                value={viewportWidth}
              >
                <Label className="text-[11px] text-muted-foreground" htmlFor="viewportWidth">
                  Width
                </Label>
                <NumberFieldGroup>
                  <NumberFieldDecrement />
                  <NumberFieldInput aria-label="Viewport width" />
                  <NumberFieldIncrement />
                </NumberFieldGroup>
              </NumberField>
              <NumberField
                className="grid grid-cols-[3rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1"
                format={{ useGrouping: false }}
                id="viewportHeight"
                largeStep={100}
                min={1}
                onValueChange={(value) => {
                  setViewportDirty(true);
                  setViewportHeight(value);
                }}
                size="sm"
                value={viewportHeight}
              >
                <Label className="text-[11px] text-muted-foreground" htmlFor="viewportHeight">
                  Height
                </Label>
                <NumberFieldGroup>
                  <NumberFieldDecrement />
                  <NumberFieldInput aria-label="Viewport height" />
                  <NumberFieldIncrement />
                </NumberFieldGroup>
              </NumberField>
              <NumberField
                className="grid grid-cols-[3rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1"
                format={{ maximumFractionDigits: 2 }}
                id="uiScale"
                largeStep={0.5}
                min={0.1}
                onValueChange={(value) => {
                  setViewportDirty(true);
                  setScale(value);
                }}
                size="sm"
                smallStep={0.05}
                step={0.1}
                value={scale}
              >
                <Label className="text-[11px] text-muted-foreground" htmlFor="uiScale">
                  Scale
                </Label>
                <NumberFieldGroup>
                  <NumberFieldDecrement />
                  <NumberFieldInput aria-label="UI scale" />
                  <NumberFieldIncrement />
                </NumberFieldGroup>
              </NumberField>
            </div>
            <Button
              disabled={!canResize}
              onClick={() => {
                const nextWidth = integer(viewportWidth);
                const nextHeight = integer(viewportHeight);
                const uiScale = finiteNumber(scale);
                if (nextWidth !== undefined && nextHeight !== undefined && uiScale !== undefined) {
                  void runAction({
                    schemaVersion: 1,
                    action: "resizeViewport",
                    width: nextWidth,
                    height: nextHeight,
                    uiScale,
                  }).then((result) => {
                    if (result !== undefined) {
                      setViewportDirty(false);
                    }
                  });
                }
              }}
              size="xs"
              variant="outline"
            >
              Apply viewport
            </Button>
          </fieldset>
          <fieldset className="grid gap-2">
            <legend className="font-medium text-[11px] text-muted-foreground uppercase tracking-[0.08em]">
              Subject
            </legend>
            <div className="grid gap-1.5">
              <NumberField
                className="grid grid-cols-[3rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1"
                format={{ useGrouping: false }}
                id="subjectWidth"
                largeStep={100}
                min={1}
                onValueChange={(value) => {
                  setSubjectDirty(true);
                  setSubjectWidth(value);
                }}
                size="sm"
                value={subjectWidth}
              >
                <Label className="text-[11px] text-muted-foreground" htmlFor="subjectWidth">
                  Width
                </Label>
                <NumberFieldGroup>
                  <NumberFieldDecrement />
                  <NumberFieldInput aria-label="Subject width" />
                  <NumberFieldIncrement />
                </NumberFieldGroup>
              </NumberField>
              <NumberField
                className="grid grid-cols-[3rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1"
                format={{ useGrouping: false }}
                id="subjectHeight"
                largeStep={100}
                min={1}
                onValueChange={(value) => {
                  setSubjectDirty(true);
                  setSubjectHeight(value);
                }}
                size="sm"
                value={subjectHeight}
              >
                <Label className="text-[11px] text-muted-foreground" htmlFor="subjectHeight">
                  Height
                </Label>
                <NumberFieldGroup>
                  <NumberFieldDecrement />
                  <NumberFieldInput aria-label="Subject height" />
                  <NumberFieldIncrement />
                </NumberFieldGroup>
              </NumberField>
            </div>
            <Button
              disabled={!canResizeSubject}
              onClick={() => {
                const nextWidth = integer(subjectWidth);
                const nextHeight = integer(subjectHeight);
                if (nextWidth !== undefined && nextHeight !== undefined) {
                  void runAction({
                    schemaVersion: 1,
                    action: "resizeSubject",
                    width: nextWidth,
                    height: nextHeight,
                  }).then((result) => {
                    if (result !== undefined) {
                      setSubjectDirty(false);
                    }
                  });
                }
              }}
              size="xs"
              variant="outline"
            >
              Apply subject size
            </Button>
          </fieldset>
        </div>
      </PopoverPopup>
    </Popover>
  );
}
