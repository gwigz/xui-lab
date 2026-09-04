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

  function switchSubject(subject: string | null): void {
    if (state === null || subject === null || subject === state.subject) {
      return;
    }
    void runAction({ schemaVersion: 1, action: "switch", subject, fixture: "" });
  }

  function switchFixture(value: string | null): void {
    if (state === null) {
      return;
    }
    const fixture = value ?? "";
    if (fixture === state.fixture) {
      return;
    }
    void runAction({ schemaVersion: 1, action: "switch", subject: state.subject, fixture });
  }

  return (
    <Toolbar
      aria-label="Runtime controls"
      className="w-full shrink-0 flex-wrap gap-1 rounded-none border-0 border-border border-b bg-card px-3 py-2"
    >
      <ToolbarGroup className="min-w-0 flex-wrap">
        <Select
          disabled={state === null}
          onValueChange={switchSubject}
          value={state?.subject ?? null}
        >
          <SelectTrigger aria-label="Subject" className="w-44" size="xs">
            <SelectValue placeholder="No subjects" />
          </SelectTrigger>
          <SelectPopup>
            {(state?.subjects ?? []).map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectPopup>
        </Select>
        <Select
          disabled={state === null}
          onValueChange={switchFixture}
          value={state === null || state.fixture === "" ? null : state.fixture}
        >
          <SelectTrigger aria-label="Fixture" className="w-44" size="xs">
            <SelectValue placeholder="No fixture" />
          </SelectTrigger>
          <SelectPopup>
            <SelectItem value={null}>No fixture</SelectItem>
            {(state?.fixtures ?? []).map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectPopup>
        </Select>
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
      <ToolbarGroup className="ml-auto shrink-0">
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
      </ToolbarGroup>
    </Toolbar>
  );
}
