import { useEffect, useMemo, useRef, useState } from "react";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
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

  return (
    <aside className="flex h-full min-h-0 flex-col bg-card">
      <section className="flex min-h-0 flex-1 flex-col p-2">
        <div className="px-1.5 pb-2 pt-1">
          <ToggleGroup
            aria-label="Tree visibility"
            multiple
            onValueChange={(values) =>
              setFilter({
                showHidden: values.includes("hidden"),
                showLabRoots: values.includes("roots"),
                showMenus: values.includes("menus"),
              })
            }
            size="sm"
            value={[
              ...(filter.showHidden ? ["hidden"] : []),
              ...(filter.showMenus ? ["menus"] : []),
              ...(filter.showLabRoots ? ["roots"] : []),
            ]}
            variant="outline"
          >
            <ToggleGroupItem value="hidden">Hidden</ToggleGroupItem>
            <ToggleGroupItem value="menus">Menus</ToggleGroupItem>
            <ToggleGroupItem value="roots">Roots</ToggleGroupItem>
          </ToggleGroup>
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
