import { Columns2, Crosshair, ImagePlus, Layers2, Maximize2, Minimize2, X } from "lucide-react";
import {
  type ChangeEvent,
  type MouseEvent,
  type PointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useRef,
  useState,
  type WheelEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { Slider, SliderPrimitive, SliderValue } from "@/components/ui/slider";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  findModelTreeNodeAtPoint,
  findTreeNodeAtPoint,
  findTreeNodeByControlId,
  type InspectorState,
  recordValue,
  treeNodeVisibleRect,
} from "../contracts";
import {
  browserFrameInput,
  type FrameOutline,
  type FramePoint,
  frameDragInput,
  frameOutline,
  framePoint,
  wheelClicks,
} from "../frame-interaction";
import type { InspectorTab, RunInspectorAction } from "../model";
import { DisplaySettings } from "./display-settings";
import { Filmstrip, type FilmstripVersion } from "./filmstrip";

const tabs = [
  { id: "snapshot", label: "Snapshot" },
  { id: "selected", label: "Selected Control" },
  { id: "focus", label: "Active Focus" },
  { id: "recording", label: "Recorded Python" },
] satisfies readonly Readonly<{ id: InspectorTab; label: string }>[];

function json(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? "null";
}

function isInspectorTab(value: unknown): value is InspectorTab {
  return tabs.some((tab) => tab.id === value);
}

type SnapshotProps = Readonly<{
  state: InspectorState | null;
  selectedControlId: string;
  runAction: RunInspectorAction;
  onSelectedControlId: (controlId: string) => void;
  filmstripVersion: FilmstripVersion;
  onFilmstripVersion: (version: FilmstripVersion) => void;
  historical: boolean;
}>;

function Snapshot({
  state,
  selectedControlId,
  runAction,
  onSelectedControlId,
  filmstripVersion,
  onFilmstripVersion,
  historical,
}: SnapshotProps) {
  const [expanded, setExpanded] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [reference, setReference] = useState<Readonly<{ name: string; url: string }> | null>(null);
  const [referenceMode, setReferenceMode] = useState<"side" | "overlay">("side");
  const [referenceOpacity, setReferenceOpacity] = useState(50);
  const [hovered, setHovered] = useState<
    Readonly<{ controlId: string; outline: FrameOutline }> | undefined
  >();
  const container = useRef<HTMLDivElement>(null);
  const referenceInput = useRef<HTMLInputElement>(null);
  const pointerStart = useRef<Readonly<{
    pointerId: number;
    point: FramePoint;
    sourceControlId?: string | undefined;
    sourceModelId?: string | undefined;
  }> | null>(null);
  const suppressClick = useRef(false);
  const inputQueue = useRef<Promise<void>>(Promise.resolve());
  const selectedControlIdRef = useRef(selectedControlId);
  const capture = state?.capture;
  const captureVersion =
    filmstripVersion === "live"
      ? capture?.kind === "available"
        ? capture.version
        : 0
      : filmstripVersion;
  const viewport = recordValue(state?.diagnostics.viewport);
  const lluiWidth = typeof viewport?.lluiWidth === "number" ? viewport.lluiWidth : 0;
  const lluiHeight = typeof viewport?.lluiHeight === "number" ? viewport.lluiHeight : 0;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }
      if (inspecting) {
        setInspecting(false);
        setHovered(undefined);
        return;
      }
      if (expanded) {
        setExpanded(false);
        return;
      }
      if (historical) {
        onFilmstripVersion("live");
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [expanded, historical, inspecting, onFilmstripVersion]);

  useEffect(() => {
    selectedControlIdRef.current = selectedControlId;
  }, [selectedControlId]);

  useEffect(() => {
    if (historical) {
      setInspecting(false);
      setHovered(undefined);
    }
  }, [historical]);

  useEffect(() => {
    const url = reference?.url;
    return () => {
      if (url !== undefined) {
        URL.revokeObjectURL(url);
      }
    };
  }, [reference?.url]);

  if (capture?.kind !== "available") {
    return (
      <div className="grid h-full min-h-44 place-items-center rounded-xl border border-dashed border-white/10 bg-black/20 px-6 text-center text-[13px] text-neutral-600">
        Interact with the viewer to capture frames.
      </div>
    );
  }

  function point(event: MouseEvent<HTMLImageElement>): FramePoint | undefined {
    if (lluiWidth <= 0 || lluiHeight <= 0) {
      return undefined;
    }
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) {
      return undefined;
    }
    return framePoint(event.clientX, event.clientY, bounds, lluiWidth, lluiHeight);
  }

  function updateHovered(event: PointerEvent<HTMLImageElement>) {
    if (!inspecting || state === null || container.current === null) {
      return;
    }
    const targetPoint = point(event);
    if (targetPoint === undefined) {
      setHovered(undefined);
      return;
    }
    const target = findTreeNodeAtPoint(state.tree, targetPoint);
    const rect = target === undefined ? undefined : treeNodeVisibleRect(target);
    if (target === undefined || rect === undefined) {
      setHovered(undefined);
      return;
    }
    setHovered({
      controlId: target.controlId,
      outline: frameOutline(
        rect,
        event.currentTarget.getBoundingClientRect(),
        container.current.getBoundingClientRect(),
        lluiWidth,
        lluiHeight,
      ),
    });
  }

  function pressKey(event: ReactKeyboardEvent<HTMLImageElement>) {
    if (inspecting || historical || !state?.inputOperations.includes("key")) {
      return;
    }
    const input = browserFrameInput({
      key: event.key,
      shiftKey: event.shiftKey,
      ctrlKey: event.ctrlKey,
      altKey: event.altKey,
      metaKey: event.metaKey,
      isComposing: event.nativeEvent.isComposing,
    });
    if (input === undefined) {
      return;
    }
    const operation = input.action === "type" ? "text" : "key";
    if (!state.inputOperations.includes(operation)) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    enqueueInput(async () => {
      const controlId = selectedControlIdRef.current;
      if (controlId.length === 0) {
        return;
      }
      const selector = state.locators[controlId]?.selector;
      if (selector === undefined) {
        return;
      }
      await runAction(
        input.action === "type"
          ? { schemaVersion: 1, action: "type", selector, text: input.text }
          : {
              schemaVersion: 1,
              action: "press",
              selector,
              key: input.key,
              modifiers: input.modifiers,
            },
      );
    });
  }

  function enqueueInput(task: () => Promise<void>) {
    inputQueue.current = inputQueue.current.catch(() => undefined).then(task);
  }

  function selectActionTarget(result: Readonly<Record<string, unknown>> | undefined) {
    if (typeof result?.controlId === "string" && result.controlId.length > 0) {
      selectedControlIdRef.current = result.controlId;
      onSelectedControlId(result.controlId);
    }
  }

  function clickAt(target: FramePoint) {
    enqueueInput(async () => {
      const result = recordValue(
        await runAction({ schemaVersion: 1, action: "clickAt", x: target.x, y: target.y }),
      );
      selectActionTarget(result);
    });
  }

  function doubleClickAt(target: FramePoint) {
    enqueueInput(async () => {
      const result = recordValue(
        await runAction({ schemaVersion: 1, action: "doubleClickAt", x: target.x, y: target.y }),
      );
      selectActionTarget(result);
    });
  }

  async function finishGesture(event: PointerEvent<HTMLImageElement>) {
    const start = pointerStart.current;
    const end = point(event);
    pointerStart.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (start === null || start.pointerId !== event.pointerId || end === undefined) {
      return;
    }

    if (inspecting) {
      setInspecting(false);
      setHovered(undefined);
      if (historical) {
        const target = state === null ? undefined : findTreeNodeAtPoint(state.tree, end);
        if (target !== undefined) {
          onSelectedControlId(target.controlId);
        }
        return;
      }
      const result = recordValue(
        await runAction({ schemaVersion: 1, action: "pick", x: end.x, y: end.y }, "selected"),
      );
      if (typeof result?.control_id === "string") {
        onSelectedControlId(result.control_id);
      }
      return;
    }

    if (historical) {
      return;
    }

    const distance = Math.hypot(end.x - start.point.x, end.y - start.point.y);
    if (distance < 3) {
      suppressClick.current = false;
      return;
    }
    suppressClick.current = true;
    const targetNode = state === null ? undefined : findTreeNodeAtPoint(state.tree, end);
    const input = frameDragInput({
      start: start.point,
      end,
      sourceControlId: start.sourceControlId,
      sourceModelId: start.sourceModelId,
      targetControlId: targetNode?.controlId,
      supportsDragAndDrop: state?.inputOperations.includes("dragAndDrop") ?? false,
    });
    enqueueInput(async () => {
      await runAction(input);
    });
  }

  function wheel(event: WheelEvent<HTMLImageElement>) {
    if (inspecting || historical || !state?.inputOperations.includes("scroll")) {
      return;
    }
    const target = point(event);
    const clicks = wheelClicks(event.deltaY);
    if (target === undefined || clicks === 0) {
      return;
    }
    event.preventDefault();
    enqueueInput(async () => {
      await runAction({
        schemaVersion: 1,
        action: "scrollAt",
        x: target.x,
        y: target.y,
        clicks,
      });
    });
  }

  function clicked(event: MouseEvent<HTMLImageElement>) {
    if (inspecting || historical) {
      return;
    }
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    const target = point(event);
    if (target === undefined || event.detail !== 1) {
      return;
    }
    clickAt(target);
  }

  function doubleClicked(event: MouseEvent<HTMLImageElement>) {
    if (inspecting || historical) {
      return;
    }
    event.preventDefault();
    const target = point(event);
    if (target !== undefined) {
      doubleClickAt(target);
    }
  }

  function rightClick(event: MouseEvent<HTMLImageElement>) {
    if (inspecting || historical) {
      return;
    }
    event.preventDefault();
    event.currentTarget.focus();
    const target = point(event);
    if (target === undefined) {
      return;
    }
    enqueueInput(async () => {
      const result = recordValue(
        await runAction({ schemaVersion: 1, action: "rightClickAt", x: target.x, y: target.y }),
      );
      selectActionTarget(result);
    });
  }

  function loadReference(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (file === undefined) {
      return;
    }
    setReference({ name: file.name, url: URL.createObjectURL(file) });
  }

  return (
    <div
      className={cn(
        "flex min-h-0 min-w-0 flex-col overflow-hidden bg-black",
        expanded
          ? "fixed inset-0 z-50 h-dvh w-dvw"
          : "relative min-h-0 flex-1 rounded-xl border border-white/8",
      )}
      data-expanded={expanded}
    >
      <div className="relative z-10 flex shrink-0 items-center justify-between gap-2 px-3 py-2">
        <div className="flex items-center gap-1">
          <Button
            aria-label="Inspect"
            aria-pressed={inspecting}
            onClick={() => {
              setHovered(undefined);
              setInspecting((value) => !value);
            }}
            size="icon-xs"
            variant={inspecting ? "default" : "outline"}
          >
            <Crosshair aria-hidden size={14} />
          </Button>
          <input
            accept="image/*"
            className="hidden"
            onChange={loadReference}
            ref={referenceInput}
            type="file"
          />
          <Button onClick={() => referenceInput.current?.click()} size="xs" variant="outline">
            <ImagePlus aria-hidden size={14} />
            Reference
          </Button>
        </div>
        <div className="flex gap-1">
          <DisplaySettings runAction={runAction} state={state} />
          <Button
            aria-pressed={expanded}
            onClick={() => setExpanded((value) => !value)}
            size="xs"
            variant="outline"
          >
            {expanded ? <Minimize2 aria-hidden size={14} /> : <Maximize2 aria-hidden size={14} />}
            {expanded ? "Exit Fullscreen" : "Fullscreen"}
          </Button>
        </div>
      </div>
      {reference === null ? null : (
        <fieldset
          aria-label="Reference comparison controls"
          className="flex min-w-0 shrink-0 items-center gap-1 border-white/8 border-t px-3 py-1.5"
        >
          <span className="min-w-0 flex-1 truncate text-[11px] text-neutral-500">
            Visual aid only · {reference.name}
          </span>
          <Button
            aria-pressed={referenceMode === "side"}
            onClick={() => setReferenceMode("side")}
            size="xs"
            variant={referenceMode === "side" ? "secondary" : "outline"}
          >
            <Columns2 aria-hidden size={13} />
            Side by side
          </Button>
          <Button
            aria-pressed={referenceMode === "overlay"}
            onClick={() => setReferenceMode("overlay")}
            size="xs"
            variant={referenceMode === "overlay" ? "secondary" : "outline"}
          >
            <Layers2 aria-hidden size={13} />
            Overlay
          </Button>
          {referenceMode === "overlay" ? (
            <Slider
              className="w-28 px-1"
              max={100}
              min={0}
              onValueChange={(value) => {
                if (typeof value === "number") {
                  setReferenceOpacity(value);
                }
              }}
              step={5}
              value={referenceOpacity}
            >
              <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-neutral-500">
                <SliderPrimitive.Label>Opacity</SliderPrimitive.Label>
                <SliderValue className="text-[11px] tabular-nums" />
              </div>
            </Slider>
          ) : null}
          <Button
            aria-label="Remove reference"
            onClick={() => setReference(null)}
            size="icon-xs"
            variant="ghost"
          >
            <X aria-hidden size={13} />
          </Button>
        </fieldset>
      )}
      <div
        className={cn(
          "flex min-h-0 min-w-0 flex-1 overflow-hidden",
          reference !== null && referenceMode === "side" && "gap-px bg-white/10",
        )}
      >
        <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden bg-black" ref={container}>
          {hovered === undefined ? null : (
            <div
              aria-hidden
              className="pointer-events-none absolute z-[5] border-2 border-sky-400 bg-sky-400/10 shadow-[0_0_0_1px_rgba(2,6,23,0.85)]"
              data-hovered-control-id={hovered.controlId}
              style={hovered.outline}
            />
          )}
          <img
            alt="xui-lab screenshot"
            className={cn(
              "absolute inset-0 m-auto max-h-full max-w-full touch-none select-none object-contain outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 focus-visible:ring-offset-black",
              inspecting ? "cursor-crosshair" : "cursor-default",
            )}
            draggable={false}
            onClick={clicked}
            onContextMenu={rightClick}
            onDoubleClick={doubleClicked}
            onKeyDown={pressKey}
            onLoad={() => setHovered(undefined)}
            onPointerCancel={() => {
              pointerStart.current = null;
            }}
            onPointerDown={(event) => {
              if (!inspecting && !historical) {
                event.currentTarget.focus();
              }
              if (event.button !== 0) {
                return;
              }
              const start = point(event);
              if (start !== undefined) {
                const sourceNode =
                  state === null
                    ? undefined
                    : (findModelTreeNodeAtPoint(state.tree, start) ??
                      findTreeNodeAtPoint(state.tree, start));
                const modelId = sourceNode?.raw.model_id;
                event.currentTarget.setPointerCapture(event.pointerId);
                pointerStart.current = {
                  pointerId: event.pointerId,
                  point: start,
                  sourceControlId: sourceNode?.controlId,
                  sourceModelId: typeof modelId === "string" ? modelId : undefined,
                };
              }
            }}
            onPointerLeave={() => setHovered(undefined)}
            onPointerMove={updateHovered}
            onPointerUp={(event) => void finishGesture(event)}
            onWheel={wheel}
            src={`/api/v1/captures/${String(captureVersion)}`}
            tabIndex={!historical && !inspecting && state?.inputOperations.includes("key") ? 0 : -1}
          />
          {reference !== null && referenceMode === "overlay" ? (
            <img
              alt={`Reference: ${reference.name}`}
              className="pointer-events-none absolute inset-0 z-[1] m-auto max-h-full max-w-full select-none object-contain"
              draggable={false}
              src={reference.url}
              style={{ opacity: referenceOpacity / 100 }}
            />
          ) : null}
        </div>
        {reference !== null && referenceMode === "side" ? (
          <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden bg-black">
            <img
              alt={`Reference: ${reference.name}`}
              className="absolute inset-0 m-auto max-h-full max-w-full select-none object-contain"
              draggable={false}
              src={reference.url}
            />
          </div>
        ) : null}
      </div>
      <div className="min-w-0 shrink-0">
        <Filmstrip
          captures={state?.captures ?? []}
          frameHeight={lluiHeight}
          frameWidth={lluiWidth}
          onVersion={onFilmstripVersion}
          version={filmstripVersion}
        />
      </div>
    </div>
  );
}

function JsonPanel({ value }: Readonly<{ value: unknown }>) {
  return (
    <pre className="h-full min-h-0 overflow-auto rounded-xl border border-border bg-card p-3 font-mono text-[12px] text-foreground leading-5">
      {json(value)}
    </pre>
  );
}

function SelectedControl({ value }: Readonly<{ value: Readonly<Record<string, unknown>> }>) {
  const rect = recordValue(value.screen_rect);
  return (
    <div className="h-full min-h-0 overflow-auto rounded-xl border border-border bg-card p-3 text-[12px] text-foreground">
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
        <dt className="text-muted-foreground">Control ID</dt>
        <dd className="truncate font-mono">{String(value.control_id ?? "—")}</dd>
        <dt className="text-muted-foreground">Path</dt>
        <dd className="truncate font-mono">{String(value.path ?? "—")}</dd>
        <dt className="text-muted-foreground">Class</dt>
        <dd>{String(value.class ?? "—").replace(/^\d+/, "")}</dd>
        <dt className="text-muted-foreground">Screen rect</dt>
        <dd className="font-mono">
          {rect === undefined
            ? "—"
            : `${String(rect.left)},${String(rect.bottom)} → ${String(rect.right)},${String(rect.top)}`}
        </dd>
      </dl>
      <pre className="mt-4 overflow-auto border-border border-t pt-3 font-mono text-[11px] leading-5">
        {json(value)}
      </pre>
    </div>
  );
}

type DiagnosticsProps = Readonly<{
  state: InspectorState | null;
  selectedControlId: string;
  runAction: RunInspectorAction;
  onSelectedControlId: (controlId: string) => void;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  filmstripVersion: FilmstripVersion;
  onFilmstripVersion: (version: FilmstripVersion) => void;
  historical: boolean;
}>;

export function Diagnostics({
  state,
  selectedControlId,
  runAction,
  onSelectedControlId,
  tab,
  onTab,
  filmstripVersion,
  onFilmstripVersion,
  historical,
}: DiagnosticsProps) {
  const selected =
    state === null ? {} : (findTreeNodeByControlId(state.tree, selectedControlId)?.raw ?? {});
  const overlay = recordValue(state?.diagnostics.overlay) ?? {};
  const focus = {
    focus: state?.diagnostics.focus ?? null,
    mouseCapture: state?.diagnostics.mouseCapture ?? null,
    viewport: state?.diagnostics.viewport ?? null,
    overlay,
  };

  return (
    <Tabs
      className="mt-2 min-h-0 min-w-0 flex-1 gap-2 overflow-hidden"
      onValueChange={(value) => {
        if (isInspectorTab(value)) {
          onTab(value);
        }
      }}
      value={tab}
    >
      <TabsList
        aria-label="Inspector views"
        className="max-w-full shrink-0 justify-start overflow-x-auto"
        size="xs"
      >
        {tabs.map((item) => (
          <TabsTab id={`${item.id}Tab`} key={item.id} value={item.id}>
            {item.label}
          </TabsTab>
        ))}
      </TabsList>

      <TabsPanel
        className="flex min-h-0 min-w-0 flex-col overflow-hidden"
        id="snapshotPanel"
        value="snapshot"
      >
        <Snapshot
          filmstripVersion={filmstripVersion}
          historical={historical}
          onFilmstripVersion={onFilmstripVersion}
          onSelectedControlId={onSelectedControlId}
          runAction={runAction}
          selectedControlId={selectedControlId}
          state={state}
        />
      </TabsPanel>
      <TabsPanel className="min-h-0 min-w-0 overflow-hidden" id="selectedPanel" value="selected">
        <SelectedControl value={selected} />
      </TabsPanel>
      <TabsPanel className="min-h-0 min-w-0 overflow-hidden" id="focusPanel" value="focus">
        <JsonPanel value={focus} />
      </TabsPanel>
      <TabsPanel className="min-h-0 min-w-0 overflow-hidden" id="recordingPanel" value="recording">
        <Textarea
          aria-label="Recorded Python"
          className="h-full min-h-0 rounded-xl [&>textarea]:h-full [&>textarea]:resize-none [&>textarea]:overflow-auto [&>textarea]:p-3 [&>textarea]:font-mono [&>textarea]:text-[12px] [&>textarea]:leading-5"
          defaultValue={state?.recording.join("\n") ?? ""}
          key={state?.recording.join("\n") ?? ""}
          spellCheck={false}
        />
      </TabsPanel>
    </Tabs>
  );
}
