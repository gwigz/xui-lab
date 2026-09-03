import { Camera, Copy, FileJson, MousePointer2, Play, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectItem,
  SelectPopup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Toolbar, ToolbarGroup, ToolbarSeparator } from "@/components/ui/toolbar";
import { type InspectorState, recordValue, reviewableLocatorPython } from "../contracts";
import type { InspectorStatus, RunInspectorAction } from "../model";

function integer(value: string): number | undefined {
  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : undefined;
}

function finiteNumber(value: string): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

type InspectorToolbarProps = Readonly<{
  state: InspectorState | null;
  selectedControlId: string;
  runAction: RunInspectorAction;
  onSelectedControlId: (controlId: string) => void;
  onStatus: (status: InspectorStatus) => void;
}>;

export function InspectorToolbar({
  state,
  selectedControlId,
  runAction,
  onSelectedControlId,
  onStatus,
}: InspectorToolbarProps) {
  const [viewportWidth, setViewportWidth] = useState("800");
  const [viewportHeight, setViewportHeight] = useState("600");
  const [scale, setScale] = useState("1");
  const [viewportDirty, setViewportDirty] = useState(false);
  const [subjectWidth, setSubjectWidth] = useState("");
  const [subjectHeight, setSubjectHeight] = useState("");
  const [subjectDirty, setSubjectDirty] = useState(false);
  const [pickX, setPickX] = useState("");
  const [pickY, setPickY] = useState("");
  const [text, setText] = useState("");
  const [key, setKey] = useState("Enter");
  const [scenario, setScenario] = useState("");

  useEffect(() => {
    if (state !== null && !state.scenarios.includes(scenario)) {
      setScenario(state.scenarios[0] ?? "");
    }
  }, [scenario, state]);

  useEffect(() => {
    if (state === null || viewportDirty) {
      return;
    }
    const viewport = recordValue(state.diagnostics.viewport);
    if (typeof viewport?.windowWidth === "number") {
      setViewportWidth(String(viewport.windowWidth));
    }
    if (typeof viewport?.windowHeight === "number") {
      setViewportHeight(String(viewport.windowHeight));
    }
    if (typeof viewport?.uiScale === "number") {
      setScale(String(viewport.uiScale));
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
      setSubjectWidth(String(rect.right - rect.left));
      setSubjectHeight(String(rect.top - rect.bottom));
    }
  }, [state, subjectDirty]);

  const canResize =
    integer(viewportWidth) !== undefined &&
    integer(viewportHeight) !== undefined &&
    finiteNumber(scale) !== undefined;
  const canResizeSubject =
    integer(subjectWidth) !== undefined && integer(subjectHeight) !== undefined;
  const canPick = integer(pickX) !== undefined && integer(pickY) !== undefined;
  const selected = selectedControlId.length > 0;
  const selectedSelector = state?.locators[selectedControlId]?.selector;
  const supports = (operation: string) => state?.inputOperations.includes(operation) ?? false;

  async function pickControl() {
    const x = integer(pickX);
    const y = integer(pickY);
    if (x === undefined || y === undefined) {
      return;
    }
    const result = await runAction({ action: "pick", x, y }, "selected");
    const resultControlId = recordValue(result)?.control_id;
    if (typeof resultControlId === "string") {
      onSelectedControlId(resultControlId);
    }
  }

  async function copyLocator() {
    if (!selected) {
      return;
    }
    try {
      const locator = state?.locators[selectedControlId];
      if (locator === undefined) {
        throw new Error("Selected control has no ranked locator");
      }
      const fallback = locator.fallbackReason ?? "none";
      await navigator.clipboard.writeText(reviewableLocatorPython(locator));
      onStatus({
        kind: "ready",
        message: `Locator copied · ${locator.signals.join(" + ")} · ${locator.matchCount} match${locator.matchCount === 1 ? "" : "es"} · fallback: ${fallback}`,
      });
    } catch (error) {
      onStatus({
        kind: "error",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return (
    <div className="shrink-0 rounded-xl border border-border bg-card p-1.5">
      <Toolbar
        aria-label="Runtime controls"
        className="flex-wrap gap-1 border-0 bg-transparent p-0"
      >
        <ToolbarGroup>
          <Button onClick={() => void runAction({ action: "reload" })} size="xs" variant="outline">
            <RefreshCw aria-hidden size={14} /> Reload XUI
          </Button>
          <Button onClick={() => void runAction({ action: "capture" }, "snapshot")} size="xs">
            <Camera aria-hidden size={14} /> Screenshot
          </Button>
          <Button onClick={() => void runAction({ action: "export" })} size="xs" variant="outline">
            <FileJson aria-hidden size={14} /> Export Tree
          </Button>
          <Button
            disabled={!selected}
            onClick={() => void copyLocator()}
            size="xs"
            variant="outline"
          >
            <Copy aria-hidden size={14} /> Copy Locator
          </Button>
        </ToolbarGroup>

        <ToolbarSeparator orientation="vertical" />

        <ToolbarGroup>
          <span className="px-1 text-[11px] text-neutral-600">Viewport</span>
          <Input
            aria-label="Viewport width"
            className="w-16"
            inputMode="numeric"
            onChange={(event) => {
              setViewportDirty(true);
              setViewportWidth(event.target.value);
            }}
            size="xs"
            type="number"
            value={viewportWidth}
          />
          <span className="text-[11px] text-neutral-600">×</span>
          <Input
            aria-label="Viewport height"
            className="w-16"
            inputMode="numeric"
            onChange={(event) => {
              setViewportDirty(true);
              setViewportHeight(event.target.value);
            }}
            size="xs"
            type="number"
            value={viewportHeight}
          />
          <Input
            aria-label="UI scale"
            className="w-12"
            onChange={(event) => {
              setViewportDirty(true);
              setScale(event.target.value);
            }}
            size="xs"
            step="0.1"
            type="number"
            value={scale}
          />
          <Button
            disabled={!canResize}
            onClick={() => {
              const nextWidth = integer(viewportWidth);
              const nextHeight = integer(viewportHeight);
              const uiScale = finiteNumber(scale);
              if (nextWidth !== undefined && nextHeight !== undefined && uiScale !== undefined) {
                void runAction({
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
        </ToolbarGroup>

        <ToolbarSeparator orientation="vertical" />

        <ToolbarGroup>
          <span className="px-1 text-[11px] text-neutral-600">Subject</span>
          <Input
            aria-label="Subject width"
            className="w-16"
            onChange={(event) => {
              setSubjectDirty(true);
              setSubjectWidth(event.target.value);
            }}
            size="xs"
            type="number"
            value={subjectWidth}
          />
          <span className="text-[11px] text-neutral-600">×</span>
          <Input
            aria-label="Subject height"
            className="w-16"
            onChange={(event) => {
              setSubjectDirty(true);
              setSubjectHeight(event.target.value);
            }}
            size="xs"
            type="number"
            value={subjectHeight}
          />
          <Button
            disabled={!canResizeSubject}
            onClick={() => {
              const nextWidth = integer(subjectWidth);
              const nextHeight = integer(subjectHeight);
              if (nextWidth !== undefined && nextHeight !== undefined) {
                void runAction({
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
        </ToolbarGroup>
      </Toolbar>

      <Toolbar
        aria-label="Input and scenario controls"
        className="mt-1 flex-wrap gap-1 border-0 border-border border-t bg-transparent p-0 pt-1"
      >
        <ToolbarGroup>
          <Input
            aria-label="Screen x coordinate"
            className="w-12"
            onChange={(event) => setPickX(event.target.value)}
            placeholder="X"
            size="xs"
            type="number"
            value={pickX}
          />
          <Input
            aria-label="Screen y coordinate"
            className="w-12"
            onChange={(event) => setPickY(event.target.value)}
            placeholder="Y"
            size="xs"
            type="number"
            value={pickY}
          />
          <Button
            disabled={!canPick}
            onClick={() => void pickControl()}
            size="xs"
            variant="outline"
          >
            <MousePointer2 aria-hidden size={14} /> Pick
          </Button>
          <Button
            disabled={selectedSelector === undefined || !supports("click")}
            onClick={() =>
              selectedSelector === undefined
                ? undefined
                : void runAction({ action: "click", selector: selectedSelector })
            }
            size="xs"
            variant="outline"
          >
            Click
          </Button>
        </ToolbarGroup>

        <ToolbarSeparator orientation="vertical" />

        <ToolbarGroup>
          <Input
            aria-label="Text to fill"
            className="w-28"
            onChange={(event) => setText(event.target.value)}
            placeholder="text"
            size="xs"
            value={text}
          />
          <Button
            disabled={selectedSelector === undefined || !supports("fill")}
            onClick={() => {
              if (selectedSelector !== undefined) {
                void runAction({ action: "fill", selector: selectedSelector, text });
              }
            }}
            size="xs"
            variant="outline"
          >
            Fill
          </Button>
          <Input
            aria-label="Key to press"
            className="w-16"
            onChange={(event) => setKey(event.target.value)}
            placeholder="key"
            size="xs"
            value={key}
          />
          <Button
            disabled={selectedSelector === undefined || key.length === 0 || !supports("key")}
            onClick={() => {
              if (selectedSelector !== undefined) {
                void runAction({ action: "press", selector: selectedSelector, key });
              }
            }}
            size="xs"
            variant="outline"
          >
            Press
          </Button>
        </ToolbarGroup>

        <ToolbarSeparator orientation="vertical" />

        <ToolbarGroup>
          <Select
            disabled={state === null}
            onValueChange={(value) => setScenario(value ?? "")}
            value={scenario === "" ? null : scenario}
          >
            <SelectTrigger aria-label="Scenario" className="max-w-40" size="xs">
              <SelectValue placeholder="No scenarios" />
            </SelectTrigger>
            <SelectPopup>
              {(state?.scenarios ?? []).map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectPopup>
          </Select>
          <Button
            disabled={scenario === ""}
            onClick={() => void runAction({ action: "replay", scenario })}
            size="xs"
            variant="outline"
          >
            <Play aria-hidden size={13} /> Replay
          </Button>
        </ToolbarGroup>
      </Toolbar>
    </div>
  );
}
