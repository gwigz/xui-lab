import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { InspectorState, TreeNode } from "../contracts";
import { filterTreeRoots, type TreeFilter } from "../tree-filter";

type ViewTreeProps = Readonly<{
  node: TreeNode;
  selectedControlId: string;
  onSelect: (controlId: string) => void;
  depth?: number;
}>;

function ViewTree({ node, selectedControlId, onSelect, depth = 0 }: ViewTreeProps) {
  const selected = node.controlId === selectedControlId;

  return (
    <>
      <button
        aria-current={selected ? "true" : undefined}
        className={cn(
          "block h-6 w-full truncate rounded-md pe-2 text-start font-mono text-[11px] text-neutral-400 outline-none transition-colors hover:bg-white/5 hover:text-neutral-200 focus-visible:ring-2 focus-visible:ring-neutral-600",
          selected && "bg-white/8 text-neutral-100",
        )}
        data-selected={selected || undefined}
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
}>;

export function Sidebar({ state, selectedControlId, onSelect }: SidebarProps) {
  const [filter, setFilter] = useState<TreeFilter>({
    showHidden: false,
    showLabRoots: false,
    showMenus: false,
  });
  const roots = useMemo(
    () => (state === null ? [] : filterTreeRoots(state, filter, selectedControlId)),
    [filter, selectedControlId, state],
  );
  const treeContainer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (selectedControlId === "" || roots.length === 0) {
      return;
    }
    treeContainer.current
      ?.querySelector<HTMLElement>("[data-selected=true]")
      ?.scrollIntoView({ block: "nearest" });
  }, [roots, selectedControlId]);

  function toggleFilter(key: keyof TreeFilter): void {
    setFilter((current) => ({ ...current, [key]: !current[key] }));
  }

  return (
    <aside className="flex h-full min-h-0 flex-col bg-card">
      <section className="flex min-h-0 flex-1 flex-col p-2">
        <div className="px-1.5 pt-1">
          <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-neutral-600">
            View tree
          </div>
          <fieldset
            aria-label="Tree visibility"
            className="flex flex-wrap gap-1 border-0 pb-2 pt-1.5"
          >
            <Button
              aria-pressed={filter.showHidden}
              className={cn(filter.showHidden && "bg-accent text-foreground")}
              onClick={() => toggleFilter("showHidden")}
              size="xs"
              variant="ghost"
            >
              Hidden
            </Button>
            <Button
              aria-pressed={filter.showMenus}
              className={cn(filter.showMenus && "bg-accent text-foreground")}
              onClick={() => toggleFilter("showMenus")}
              size="xs"
              variant="ghost"
            >
              Menus
            </Button>
            <Button
              aria-pressed={filter.showLabRoots}
              className={cn(filter.showLabRoots && "bg-accent text-foreground")}
              onClick={() => toggleFilter("showLabRoots")}
              size="xs"
              variant="ghost"
            >
              Lab roots
            </Button>
          </fieldset>
        </div>
        <div className="min-h-0 flex-1 overflow-auto overscroll-contain" ref={treeContainer}>
          {state === null ? (
            <div className="px-2 py-3 text-[12px] text-neutral-600">Connecting…</div>
          ) : roots.length === 0 ? (
            <div className="px-2 py-3 text-[12px] text-neutral-600">No matching controls</div>
          ) : (
            roots.map((root) => (
              <ViewTree
                key={root.controlId}
                node={root}
                onSelect={onSelect}
                selectedControlId={selectedControlId}
              />
            ))
          )}
        </div>
      </section>
    </aside>
  );
}
