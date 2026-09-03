import { FileJson, Play, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectItem,
  SelectPopup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Toolbar, ToolbarGroup } from "@/components/ui/toolbar";
import type { InspectorState } from "../contracts";
import type { RunInspectorAction } from "../model";

type InspectorToolbarProps = Readonly<{
  state: InspectorState | null;
  runAction: RunInspectorAction;
}>;

export function InspectorToolbar({ state, runAction }: InspectorToolbarProps) {
  const [scenario, setScenario] = useState("");

  useEffect(() => {
    if (state !== null && !state.scenarios.includes(scenario)) {
      setScenario(state.scenarios[0] ?? "");
    }
  }, [scenario, state]);

  return (
    <div className="shrink-0 rounded-xl border border-border bg-card p-1.5">
      <Toolbar
        aria-label="Runtime controls"
        className="flex-wrap gap-1 border-0 bg-transparent p-0"
      >
        <ToolbarGroup>
          <Button
            onClick={() => void runAction({ schemaVersion: 1, action: "reload" })}
            size="xs"
            variant="outline"
          >
            <RefreshCw aria-hidden size={14} /> Reload XUI
          </Button>
          <Button
            onClick={() => void runAction({ schemaVersion: 1, action: "export" })}
            size="xs"
            variant="outline"
          >
            <FileJson aria-hidden size={14} /> Export Tree
          </Button>
          <Select
            disabled={state === null}
            onValueChange={(value) => setScenario(value ?? "")}
            value={scenario === "" ? null : scenario}
          >
            <SelectTrigger aria-label="Scenario" className="w-40" size="xs">
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
            onClick={() => void runAction({ schemaVersion: 1, action: "replay", scenario })}
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
