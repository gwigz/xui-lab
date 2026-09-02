import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectItem,
  SelectPopup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { InspectorState, TreeNode } from "../contracts";

type ViewTreeProps = Readonly<{
  node: TreeNode;
  selectedControlId: string;
  onSelect: (controlId: string) => void;
  depth?: number;
}>;

function ViewTree({ node, selectedControlId, onSelect, depth = 0 }: ViewTreeProps) {
  return (
    <>
      <button
        className={cn(
          "block h-6 w-full truncate rounded-md pe-2 text-start font-mono text-[11px] text-neutral-400 outline-none transition-colors hover:bg-white/5 hover:text-neutral-200 focus-visible:ring-2 focus-visible:ring-neutral-600",
          node.controlId === selectedControlId && "bg-white/8 text-neutral-100",
        )}
        onClick={() => onSelect(node.controlId)}
        style={{ paddingInlineStart: `${10 + depth * 14}px` }}
        title={node.path}
        type="button"
      >
        {node.title}
      </button>
      {node.children.map((child) => (
        <ViewTree
          depth={depth + 1}
          key={child.controlId}
          node={child}
          onSelect={onSelect}
          selectedControlId={selectedControlId}
        />
      ))}
    </>
  );
}

type SidebarProps = Readonly<{
  state: InspectorState | null;
  selectedControlId: string;
  onSelect: (controlId: string) => void;
  onSwitch: (subject: string, fixture: string) => void;
}>;

export function Sidebar({ state, selectedControlId, onSelect, onSwitch }: SidebarProps) {
  const [subject, setSubject] = useState("");
  const [fixture, setFixture] = useState("");

  useEffect(() => {
    if (state !== null && !state.subjects.includes(subject)) {
      setSubject(state.subjects[0] ?? "");
    }
    if (state !== null && fixture !== "" && !state.fixtures.includes(fixture)) {
      setFixture("");
    }
  }, [fixture, state, subject]);

  return (
    <aside className="flex min-h-0 flex-col border-border border-e bg-card">
      <section className="shrink-0 border-b border-white/6 p-3">
        <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.08em] text-neutral-600">
          Subject
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-1.5">
          <Select
            disabled={state === null}
            onValueChange={(value) => setSubject(value ?? "")}
            value={subject === "" ? null : subject}
          >
            <SelectTrigger aria-label="Subject" size="xs">
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
          <Button disabled={subject === ""} onClick={() => onSwitch(subject, fixture)} size="xs">
            Open
          </Button>
          <div className="col-span-2">
            <Select
              disabled={state === null}
              onValueChange={(value) => setFixture(value ?? "")}
              value={fixture === "" ? null : fixture}
            >
              <SelectTrigger aria-label="Fixture" size="xs">
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
          </div>
        </div>
      </section>

      <section className="flex min-h-0 flex-1 flex-col p-2">
        <div className="px-1.5 pb-2 pt-1 text-[11px] font-medium uppercase tracking-[0.08em] text-neutral-600">
          View tree
        </div>
        <div className="min-h-0 flex-1 overflow-auto overscroll-contain">
          {state === null ? (
            <div className="px-2 py-3 text-[12px] text-neutral-600">Connecting…</div>
          ) : (
            <ViewTree node={state.tree} onSelect={onSelect} selectedControlId={selectedControlId} />
          )}
        </div>
      </section>
    </aside>
  );
}
