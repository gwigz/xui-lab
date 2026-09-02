import { Maximize2, Minimize2 } from "lucide-react";
import { type PointerEvent, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { findTreeNodeByControlId, type InspectorState, recordValue } from "../contracts";
import { type FramePoint, framePoint } from "../frame-interaction";
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
  runAction: RunInspectorAction;
  onSelectedControlId: (controlId: string) => void;
}>;

function Snapshot({ state, runAction, onSelectedControlId }: SnapshotProps) {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<"inspect" | "interact">("inspect");
  const pointerStart = useRef<Readonly<{ pointerId: number; point: FramePoint }> | null>(null);
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

  if (capture?.kind !== "available") {
    return (
      <div className="grid h-full min-h-44 place-items-center rounded-xl border border-dashed border-white/10 bg-black/20 px-6 text-center text-[13px] text-neutral-600">
        Take a screenshot to preview it here.
      </div>
    );
  }

  function point(event: PointerEvent<HTMLImageElement>): FramePoint | undefined {
    if (lluiWidth <= 0 || lluiHeight <= 0) {
      return undefined;
    }
    return framePoint(
      event.clientX,
      event.clientY,
      event.currentTarget.getBoundingClientRect(),
      lluiWidth,
      lluiHeight,
    );
  }

  async function finishGesture(event: PointerEvent<HTMLImageElement>) {
    const start = pointerStart.current;
    const end = point(event);
    pointerStart.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
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
      const result = recordValue(await runAction({ action: "clickAt", x: end.x, y: end.y }));
      if (typeof result?.controlId === "string" && result.controlId.length > 0) {
        onSelectedControlId(result.controlId);
      }
      return;
    }
    await runAction({
      action: "drag",
      startX: start.point.x,
      startY: start.point.y,
      endX: end.x,
      endY: end.y,
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
          onClick={() => setMode("inspect")}
          size="xs"
          variant={mode === "inspect" ? "default" : "outline"}
        >
          Inspect
        </Button>
        <Button
          aria-pressed={mode === "interact"}
          disabled={!state?.inputOperations.includes("click")}
          onClick={() => setMode("interact")}
          size="xs"
          variant={mode === "interact" ? "default" : "outline"}
        >
          Interact
        </Button>
      </div>
      <img
        alt="Latest xui-lab screenshot"
        className={cn(
          "block max-h-full max-w-full touch-none select-none object-contain",
          mode === "inspect" ? "cursor-crosshair" : "cursor-default",
        )}
        draggable={false}
        onPointerCancel={() => {
          pointerStart.current = null;
        }}
        onPointerDown={(event) => {
          const start = point(event);
          if (start !== undefined) {
            event.currentTarget.setPointerCapture(event.pointerId);
            pointerStart.current = { pointerId: event.pointerId, point: start };
          }
        }}
        onPointerUp={(event) => void finishGesture(event)}
        src={`/api/capture?v=${capture.version}`}
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
        <Snapshot onSelectedControlId={onSelectedControlId} runAction={runAction} state={state} />
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
