import { Settings2 } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Fieldset, FieldsetLegend } from "@/components/ui/fieldset";
import { Label } from "@/components/ui/label";
import {
  NumberField,
  NumberFieldDecrement,
  NumberFieldGroup,
  NumberFieldIncrement,
  NumberFieldInput,
} from "@/components/ui/number-field";
import { Popover, PopoverPopup, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { type InspectorState, recordValue } from "../contracts";
import { SUBJECT_SIZE_PRESETS, UI_SCALE_PRESETS, viewportAtScale } from "../display-presets";
import type { RunInspectorAction } from "../model";

function integer(value: number | null): number | undefined {
  return value !== null && Number.isInteger(value) ? value : undefined;
}

function finiteNumber(value: number | null): number | undefined {
  return value !== null && Number.isFinite(value) ? value : undefined;
}

// Bleed past the popover viewport padding so sections read as separate blocks.
const separatorClassName = "-mx-(--viewport-inline-padding) data-[orientation=horizontal]:w-auto";

type SettingProps = Readonly<{
  children: React.ReactNode;
  id: string;
  label: string;
}>;

function Setting({ children, id, label }: SettingProps) {
  return (
    <div className="grid grid-cols-[3.25rem_minmax(0,1fr)] items-center gap-3">
      <Label className="text-muted-foreground" htmlFor={id}>
        {label}
      </Label>
      {children}
    </div>
  );
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

  function resizeViewport(width: number, height: number, uiScale: number): void {
    setViewportWidth(width);
    setViewportHeight(height);
    setScale(uiScale);
    setViewportDirty(true);
    void runAction({
      schemaVersion: 1,
      action: "resizeViewport",
      width,
      height,
      uiScale,
    }).then((result) => {
      if (result !== undefined) {
        setViewportDirty(false);
      }
    });
  }

  function resizeSubject(width: number, height: number): void {
    setSubjectWidth(width);
    setSubjectHeight(height);
    setSubjectDirty(true);
    void runAction({
      schemaVersion: 1,
      action: "resizeSubject",
      width,
      height,
    }).then((result) => {
      if (result !== undefined) {
        setSubjectDirty(false);
      }
    });
  }

  return (
    <Popover>
      <PopoverTrigger render={<Button size="xs" variant="outline" />}>
        <Settings2 aria-hidden size={14} />
        Settings
      </PopoverTrigger>
      <PopoverPopup align="end" className="w-76" side="bottom">
        <PopoverTitle className="text-sm">Display</PopoverTitle>
        <Separator className={`${separatorClassName} mt-4`} />
        <Fieldset className="mt-4 grid gap-2">
          <FieldsetLegend className="text-xs">Viewport</FieldsetLegend>
          <Setting id="viewportWidth" label="Width">
            <NumberField
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
              <NumberFieldGroup>
                <NumberFieldDecrement />
                <NumberFieldInput aria-label="Viewport width" />
                <NumberFieldIncrement />
              </NumberFieldGroup>
            </NumberField>
          </Setting>
          <Setting id="viewportHeight" label="Height">
            <NumberField
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
              <NumberFieldGroup>
                <NumberFieldDecrement />
                <NumberFieldInput aria-label="Viewport height" />
                <NumberFieldIncrement />
              </NumberFieldGroup>
            </NumberField>
          </Setting>
          <Setting id="uiScale" label="Scale">
            <NumberField
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
              <NumberFieldGroup>
                <NumberFieldDecrement />
                <NumberFieldInput aria-label="UI scale" />
                <NumberFieldIncrement />
              </NumberFieldGroup>
            </NumberField>
          </Setting>
          <fieldset aria-label="UI scale presets" className="grid grid-cols-2 gap-1">
            {UI_SCALE_PRESETS.map((preset) => (
              <Button
                aria-label={`UI scale ${String(preset)}×`}
                key={preset}
                onClick={() => {
                  const width = integer(viewportWidth);
                  const height = integer(viewportHeight);
                  const currentScale = finiteNumber(scale);
                  if (width !== undefined && height !== undefined && currentScale !== undefined) {
                    const next = viewportAtScale(width, height, currentScale, preset);
                    resizeViewport(next.width, next.height, next.uiScale);
                  }
                }}
                size="xs"
                variant={scale === preset ? "secondary" : "outline"}
              >
                {preset}×
              </Button>
            ))}
          </fieldset>
          <Button
            className="mt-1 justify-self-end"
            disabled={!canResize}
            onClick={() => {
              const nextWidth = integer(viewportWidth);
              const nextHeight = integer(viewportHeight);
              const uiScale = finiteNumber(scale);
              if (nextWidth !== undefined && nextHeight !== undefined && uiScale !== undefined) {
                resizeViewport(nextWidth, nextHeight, uiScale);
              }
            }}
            size="xs"
            variant="outline"
          >
            Apply viewport
          </Button>
        </Fieldset>
        <Separator className={`${separatorClassName} my-4`} />
        <Fieldset className="grid gap-2">
          <FieldsetLegend className="text-xs">Subject</FieldsetLegend>
          <fieldset aria-label="Subject size presets" className="grid grid-cols-3 gap-1">
            {SUBJECT_SIZE_PRESETS.map((preset) => (
              <Button
                aria-label={`${preset.label} ${String(preset.width)} × ${String(preset.height)}`}
                key={preset.id}
                onClick={() => resizeSubject(preset.width, preset.height)}
                size="xs"
                variant={
                  subjectWidth === preset.width && subjectHeight === preset.height
                    ? "secondary"
                    : "outline"
                }
              >
                {preset.label}
              </Button>
            ))}
          </fieldset>
          <Setting id="subjectWidth" label="Width">
            <NumberField
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
              <NumberFieldGroup>
                <NumberFieldDecrement />
                <NumberFieldInput aria-label="Subject width" />
                <NumberFieldIncrement />
              </NumberFieldGroup>
            </NumberField>
          </Setting>
          <Setting id="subjectHeight" label="Height">
            <NumberField
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
              <NumberFieldGroup>
                <NumberFieldDecrement />
                <NumberFieldInput aria-label="Subject height" />
                <NumberFieldIncrement />
              </NumberFieldGroup>
            </NumberField>
          </Setting>
          <Button
            className="mt-1 justify-self-end"
            disabled={!canResizeSubject}
            onClick={() => {
              const nextWidth = integer(subjectWidth);
              const nextHeight = integer(subjectHeight);
              if (nextWidth !== undefined && nextHeight !== undefined) {
                resizeSubject(nextWidth, nextHeight);
              }
            }}
            size="xs"
            variant="outline"
          >
            Apply subject size
          </Button>
        </Fieldset>
      </PopoverPopup>
    </Popover>
  );
}
