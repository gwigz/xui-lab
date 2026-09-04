import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import {
  fetchCaptureSnapshot,
  fetchInspectorState,
  performAction,
  subscribeInspectorEvents,
} from "./api";
import { Diagnostics } from "./components/diagnostics";
import type { FilmstripVersion } from "./components/filmstrip";
import { InspectorToolbar } from "./components/inspector-toolbar";
import { Sidebar } from "./components/sidebar";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
  useDefaultLayout,
} from "./components/ui/resizable";
import { toastManager } from "./components/ui/toast";
import type { InspectorAction, InspectorState } from "./contracts";
import type { InspectorTab } from "./model";
import { shouldInvalidateInspectorState } from "./query";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function toastError(title: string, error: unknown): void {
  toastManager.add({
    description: errorMessage(error),
    title,
    type: "error",
  });
}

export function App() {
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: "xui-lab-inspector-shell",
  });
  const queryClient = useQueryClient();
  const stateQuery = useQuery({
    queryKey: ["inspector-state"],
    queryFn: ({ signal }) => fetchInspectorState(signal),
  });
  const state: InspectorState | null = stateQuery.data ?? null;
  const actionMutation = useMutation({ mutationFn: performAction });
  const [selectedControlId, setSelectedControlId] = useState("");
  const [tab, setTab] = useState<InspectorTab>("snapshot");
  const [filmstripVersion, setFilmstripVersion] = useState<FilmstripVersion>("live");
  const historical = filmstripVersion !== "live";
  const snapshotQuery = useQuery({
    queryKey: ["capture-snapshot", filmstripVersion],
    queryFn: () => fetchCaptureSnapshot(filmstripVersion as number),
    enabled: historical,
  });

  useEffect(() => {
    if (stateQuery.error !== null) {
      toastError("Could not load inspector state", stateQuery.error);
    }
  }, [stateQuery.error]);

  useEffect(() => {
    if (snapshotQuery.error !== null) {
      toastError("Could not load capture", snapshotQuery.error);
    }
  }, [snapshotQuery.error]);

  useEffect(() => {
    const unsubscribe = subscribeInspectorEvents(
      (event, reset) => {
        const cached = queryClient.getQueryData<InspectorState>(["inspector-state"]);
        if (shouldInvalidateInspectorState(cached?.stateVersion, event.stateVersion, reset)) {
          void queryClient.invalidateQueries({ queryKey: ["inspector-state"] });
        }
      },
      (source) => {
        if (source.readyState === EventSource.CLOSED) {
          toastError("Inspector disconnected", "inspector event stream closed");
        }
      },
    );

    return () => {
      unsubscribe();
    };
  }, [queryClient]);

  const runAction = useCallback(
    async (action: InspectorAction, nextTab?: InspectorTab): Promise<unknown> => {
      try {
        const result = await actionMutation.mutateAsync(action);
        await queryClient.invalidateQueries({ queryKey: ["inspector-state"] });
        setFilmstripVersion("live");

        if (nextTab !== undefined) {
          setTab(nextTab);
        }

        return result;
      } catch (error) {
        toastError(`${action.action} failed`, error);
        return undefined;
      }
    },
    [actionMutation, queryClient],
  );

  async function selectControl(controlId: string) {
    setSelectedControlId(controlId);
    if (historical) {
      return;
    }

    const selector = state?.locators[controlId]?.selector;

    if (selector !== undefined) {
      await runAction({ schemaVersion: 1, action: "highlight", selector }, "selected");
    }
  }

  const displayedState: InspectorState | null =
    historical && snapshotQuery.data !== undefined && state !== null
      ? {
          ...state,
          tree: snapshotQuery.data.tree,
          diagnostics: snapshotQuery.data.diagnostics,
          recording: snapshotQuery.data.recording,
          locators: snapshotQuery.data.locators,
        }
      : state;

  return (
    <div className="flex h-dvh min-h-0 flex-col bg-background text-foreground">
      <InspectorToolbar runAction={runAction} state={displayedState} />
      <ResizablePanelGroup
        className="min-h-0 min-w-0 flex-1"
        defaultLayout={defaultLayout}
        id="xui-lab-inspector-shell"
        onLayoutChanged={onLayoutChanged}
        orientation="horizontal"
      >
        <ResizablePanel
          className="min-h-0"
          defaultSize={230}
          id="inspector-sidebar"
          maxSize="50%"
          minSize={230}
        >
          <Sidebar
            onSelect={(controlId) => void selectControl(controlId)}
            selectedControlId={selectedControlId}
            state={displayedState}
          />
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel className="min-h-0 min-w-0" id="inspector-main" minSize={360}>
          <main className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
            <div className="flex min-h-0 min-w-0 flex-1 flex-col px-3 pb-3">
              <Diagnostics
                filmstripVersion={filmstripVersion}
                historical={historical}
                onFilmstripVersion={setFilmstripVersion}
                onSelectedControlId={setSelectedControlId}
                onTab={setTab}
                runAction={runAction}
                selectedControlId={selectedControlId}
                state={displayedState}
                tab={tab}
              />
            </div>
          </main>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
