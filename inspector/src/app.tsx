import { useCallback, useEffect, useState } from "react";
import { fetchInspectorState, performAction } from "./api";
import { Diagnostics } from "./components/diagnostics";
import { InspectorToolbar } from "./components/inspector-toolbar";
import { Sidebar } from "./components/sidebar";
import type { InspectorAction, InspectorState } from "./contracts";
import { cn } from "./lib/utils";
import type { InspectorStatus, InspectorTab } from "./model";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function StatusBar({ status }: Readonly<{ status: InspectorStatus }>) {
  return (
    <div
      className={cn(
        "col-span-2 flex h-8 min-w-0 items-center gap-2 border-border border-t bg-card px-3 font-mono text-[11px] max-[720px]:col-span-1",
        status.kind === "error" ? "text-destructive-foreground" : "text-muted-foreground",
      )}
      role={status.kind === "error" ? "alert" : "status"}
    >
      <span
        className={cn(
          "size-1.5 shrink-0 rounded-full",
          status.kind === "error" && "bg-red-400",
          status.kind === "busy" && "animate-pulse bg-amber-300",
          status.kind === "loading" && "animate-pulse bg-neutral-500",
          status.kind === "ready" && "bg-emerald-400",
        )}
      />
      <span className="truncate">{status.message}</span>
    </div>
  );
}

export function App() {
  const [state, setState] = useState<InspectorState | null>(null);
  const [status, setStatus] = useState<InspectorStatus>({
    kind: "loading",
    message: "Connecting…",
  });
  const [selectedControlId, setSelectedControlId] = useState("");
  const [tab, setTab] = useState<InspectorTab>("snapshot");

  const updateState = useCallback(async (signal?: AbortSignal, announce = false) => {
    try {
      const next = await fetchInspectorState(signal);
      setState(next);
      if (announce) {
        const processId = next.diagnostics.processId;
        const pid = typeof processId === "number" ? `PID ${processId} · ` : "";
        setStatus({ kind: "ready", message: `${pid}${next.artifactDir}` });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      setStatus({ kind: "error", message: errorMessage(error) });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let timeout = 0;
    let firstPoll = true;
    async function poll() {
      await updateState(controller.signal, firstPoll);
      firstPoll = false;
      if (active) {
        timeout = window.setTimeout(poll, 700);
      }
    }
    void poll();
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [updateState]);

  const runAction = useCallback(
    async (action: InspectorAction, nextTab?: InspectorTab): Promise<unknown> => {
      setStatus({ kind: "busy", message: `${action.action}…` });
      try {
        const result = await performAction(action);
        await updateState();
        setStatus({ kind: "ready", message: `${action.action} completed` });
        if (nextTab !== undefined) {
          setTab(nextTab);
        }
        return result;
      } catch (error) {
        setStatus({ kind: "error", message: errorMessage(error) });
        return undefined;
      }
    },
    [updateState],
  );

  async function selectControl(controlId: string) {
    setSelectedControlId(controlId);
    const selector = state?.locators[controlId]?.selector;
    if (selector !== undefined) {
      await runAction({ action: "highlight", selector }, "selected");
    }
  }

  return (
    <div className="grid h-dvh grid-cols-[minmax(230px,290px)_minmax(0,1fr)] grid-rows-[minmax(0,1fr)_32px] bg-background text-foreground max-[720px]:grid-cols-1 max-[720px]:grid-rows-[minmax(180px,30%)_minmax(0,1fr)_32px]">
      <Sidebar
        onSelect={(controlId) => void selectControl(controlId)}
        onSwitch={(subject, fixture) => void runAction({ action: "switch", subject, fixture })}
        selectedControlId={selectedControlId}
        state={state}
      />

      <main className="flex min-h-0 min-w-0 flex-col overflow-hidden p-3">
        <InspectorToolbar
          onSelectedControlId={setSelectedControlId}
          onStatus={setStatus}
          runAction={runAction}
          selectedControlId={selectedControlId}
          state={state}
        />
        <Diagnostics
          onSelectedControlId={setSelectedControlId}
          onTab={setTab}
          runAction={runAction}
          selectedControlId={selectedControlId}
          state={state}
          tab={tab}
        />
      </main>
      <StatusBar status={status} />
    </div>
  );
}
