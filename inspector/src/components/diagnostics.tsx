import { Maximize2, Minimize2 } from "lucide-react";
import {
  type MouseEvent,
  type PointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
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
  frameOutline,
  framePoint,
} from "../frame-interaction";
import type { InspectorTab, RunInspectorAction } from "../model";

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
}>;

function Snapshot({ state, selectedControlId, runAction, onSelectedControlId }: SnapshotProps) {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<"inspect" | "interact">("inspect");
  const [hovered, setHovered] = useState<
    Readonly<{ controlId: string; outline: FrameOutline }> | undefined
  >();
  const container = useRef<HTMLDivElement>(null);
  const pointerStart = useRef<Readonly<{ pointerId: number; point: FramePoint }> | null>(null);
  const suppressClick = useRef(false);
  const inputQueue = useRef<Promise<void>>(Promise.resolve());
  const selectedControlIdRef = useRef(selectedControlId);
  const capture = state?.capture;
  const viewport = recordValue(state?.diagnostics.viewport);
  const lluiWidth = typeof viewport?.lluiWidth === "number" ? viewport.lluiWidth : 0;
  const lluiHeight = typeof viewport?.lluiHeight === "number" ? viewport.lluiHeight : 0;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setExpanded(false);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    selectedControlIdRef.current = selectedControlId;
  }, [selectedControlId]);

  if (capture?.kind !== "available") {
    return (
      <div className="grid h-full min-h-44 place-items-center rounded-xl border border-dashed border-white/10 bg-black/20 px-6 text-center text-[13px] text-neutral-600">
        Take a screenshot to preview it here.
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
    if (mode !== "inspect" || state === null || container.current === null) {
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
    if (mode !== "interact" || !state?.inputOperations.includes("key")) {
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
      await runAction(
        input.action === "type"
          ? { action: "type", controlId, text: input.text }
          : {
              action: "press",
              controlId,
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
      const result = recordValue(await runAction({ action: "clickAt", x: target.x, y: target.y }));
      selectActionTarget(result);
    });
  }

  function doubleClickAt(target: FramePoint) {
    enqueueInput(async () => {
      const result = recordValue(
        await runAction({ action: "doubleClickAt", x: target.x, y: target.y }),
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

    if (mode === "inspect") {
      const result = recordValue(
        await runAction({ action: "pick", x: end.x, y: end.y }, "selected"),
      );
      if (typeof result?.control_id === "string") {
        onSelectedControlId(result.control_id);
      }
      return;
    }

    const distance = Math.hypot(end.x - start.point.x, end.y - start.point.y);
    if (distance < 3) {
      suppressClick.current = false;
      return;
    }
    suppressClick.current = true;
    enqueueInput(async () => {
      await runAction({
        action: "drag",
        startX: start.point.x,
        startY: start.point.y,
        endX: end.x,
        endY: end.y,
      });
    });
  }

  function clicked(event: MouseEvent<HTMLImageElement>) {
    if (mode !== "interact") {
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
    if (mode !== "interact") {
      return;
    }
    event.preventDefault();
    const target = point(event);
    if (target !== undefined) {
      doubleClickAt(target);
    }
  }

  function rightClick(event: MouseEvent<HTMLImageElement>) {
    if (mode !== "interact") {
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
        await runAction({ action: "rightClickAt", x: target.x, y: target.y }),
      );
      selectActionTarget(result);
    });
  }

  return (
    <div
      className={cn(
        "grid min-h-0 place-items-center overflow-hidden bg-black",
        expanded
          ? "fixed inset-0 z-50 h-dvh w-dvw p-4 pt-14"
          : "relative h-full min-h-44 rounded-xl border border-white/8 p-3 pt-12",
      )}
      data-expanded={expanded}
      ref={container}
    >
      <Button
        aria-pressed={expanded}
        className="absolute end-3 top-3 z-10"
        onClick={() => setExpanded((value) => !value)}
        size="xs"
        variant="outline"
      >
        {expanded ? <Minimize2 aria-hidden size={14} /> : <Maximize2 aria-hidden size={14} />}
        {expanded ? "Exit Fullscreen" : "Fullscreen"}
      </Button>
      <div className="absolute start-3 top-3 z-10 flex gap-1">
        <Button
          aria-pressed={mode === "inspect"}
          onClick={() => {
            setHovered(undefined);
            setMode("inspect");
          }}
          size="xs"
          variant={mode === "inspect" ? "default" : "outline"}
        >
          Inspect
        </Button>
        <Button
          aria-pressed={mode === "interact"}
          disabled={!state?.inputOperations.includes("click")}
          onClick={() => {
            setHovered(undefined);
            setMode("interact");
          }}
          size="xs"
          variant={mode === "interact" ? "default" : "outline"}
        >
          Interact
        </Button>
      </div>
      {hovered === undefined ? null : (
        <div
          aria-hidden
          className="pointer-events-none absolute z-[5] border-2 border-sky-400 bg-sky-400/10 shadow-[0_0_0_1px_rgba(2,6,23,0.85)]"
          data-hovered-control-id={hovered.controlId}
          style={hovered.outline}
        />
      )}
      <img
        alt="Latest xui-lab screenshot"
        className={cn(
          "block max-h-full max-w-full touch-none select-none object-contain outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 focus-visible:ring-offset-black",
          mode === "inspect" ? "cursor-crosshair" : "cursor-default",
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
          if (mode === "interact") {
            event.currentTarget.focus();
          }
          if (event.button !== 0) {
            return;
          }
          const start = point(event);
          if (start !== undefined) {
            event.currentTarget.setPointerCapture(event.pointerId);
            pointerStart.current = { pointerId: event.pointerId, point: start };
          }
        }}
        onPointerLeave={() => setHovered(undefined)}
        onPointerMove={updateHovered}
        onPointerUp={(event) => void finishGesture(event)}
        src={`/api/capture?v=${capture.version}`}
        tabIndex={mode === "interact" && state?.inputOperations.includes("key") ? 0 : -1}
      />
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
      <details className="mt-4 border-border border-t pt-3">
        <summary className="cursor-pointer text-muted-foreground">Raw runtime data</summary>
        <pre className="mt-2 overflow-auto font-mono text-[11px] leading-5">{json(value)}</pre>
      </details>
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
}>;

export function Diagnostics({
  state,
  selectedControlId,
  runAction,
  onSelectedControlId,
  tab,
  onTab,
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
      className="mt-2 min-h-0 flex-1 gap-2"
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

      <TabsPanel className="min-h-0" id="snapshotPanel" value="snapshot">
        <Snapshot
          onSelectedControlId={onSelectedControlId}
          runAction={runAction}
          selectedControlId={selectedControlId}
          state={state}
        />
      </TabsPanel>
      <TabsPanel className="min-h-0" id="selectedPanel" value="selected">
        <SelectedControl value={selected} />
      </TabsPanel>
      <TabsPanel className="min-h-0" id="focusPanel" value="focus">
        <JsonPanel value={focus} />
      </TabsPanel>
      <TabsPanel className="min-h-0" id="recordingPanel" value="recording">
        <textarea
          aria-label="Recorded Python"
          className="h-full min-h-0 w-full resize-none overflow-auto rounded-xl border border-border bg-card p-3 font-mono text-[12px] text-foreground leading-5 outline-none focus:border-ring focus:ring-3 focus:ring-ring/24"
          defaultValue={state?.recording.join("\n") ?? ""}
          key={state?.recording.join("\n") ?? ""}
          spellCheck={false}
        />
      </TabsPanel>
    </Tabs>
  );
}
