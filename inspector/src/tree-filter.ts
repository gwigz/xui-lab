import {
  findTreeNode,
  findTreeNodeByControlId,
  type InspectorState,
  recordValue,
  type TreeNode,
} from "./contracts";

export type TreeFilter = Readonly<{
  showHidden: boolean;
  showLabRoots: boolean;
  showMenus: boolean;
}>;

function filterNode(
  node: TreeNode,
  filter: TreeFilter,
  selectedBranch: ReadonlySet<string>,
): TreeNode | undefined {
  const children = node.children.flatMap((child) => {
    const filtered = filterNode(child, filter, selectedBranch);
    return filtered === undefined ? [] : [filtered];
  });

  if (
    node.raw.visible_chain === false &&
    !filter.showHidden &&
    !selectedBranch.has(node.controlId)
  ) {
    return undefined;
  }

  return { ...node, children };
}

function selectedBranch(tree: TreeNode, selectedControlId: string): ReadonlySet<string> {
  const branch = new Set<string>();

  function visit(node: TreeNode): boolean {
    let containsSelection = node.controlId === selectedControlId;
    for (const child of node.children) {
      containsSelection = visit(child) || containsSelection;
    }
    if (containsSelection) {
      branch.add(node.controlId);
    }
    return containsSelection;
  }

  if (selectedControlId !== "") {
    visit(tree);
  }
  return branch;
}

function subjectTree(state: InspectorState): TreeNode | undefined {
  const subject = recordValue(state.diagnostics.subject);
  const view = recordValue(subject?.view);
  const controlId = view?.control_id;
  if (typeof controlId === "string" && controlId.length > 0) {
    const byControlId = findTreeNodeByControlId(state.tree, controlId);
    if (byControlId !== undefined) {
      return byControlId;
    }
  }

  const path = view?.path;
  return typeof path === "string" && path.length > 0 ? findTreeNode(state.tree, path) : undefined;
}

function menuTree(tree: TreeNode): TreeNode | undefined {
  return findTreeNode(tree, "/Menu Holder");
}

function withoutMenuRoot(tree: TreeNode): TreeNode {
  return {
    ...tree,
    children: tree.children.filter((child) => child.path !== "/Menu Holder"),
  };
}

function filteredRoot(
  node: TreeNode | undefined,
  filter: TreeFilter,
  selection: ReadonlySet<string>,
): readonly TreeNode[] {
  if (node === undefined) {
    return [];
  }
  const filtered = filterNode(node, filter, selection);
  return filtered === undefined ? [] : [filtered];
}

export function filterTreeRoots(
  state: InspectorState,
  filter: TreeFilter,
  selectedControlId: string,
): readonly TreeNode[] {
  const selection = selectedBranch(state.tree, selectedControlId);
  if (filter.showLabRoots) {
    const tree = filter.showMenus ? state.tree : withoutMenuRoot(state.tree);
    return filteredRoot(tree, filter, selection);
  }

  const subject = filteredRoot(subjectTree(state) ?? state.tree, filter, selection);
  if (!filter.showMenus) {
    return subject;
  }
  return [...subject, ...filteredRoot(menuTree(state.tree), filter, selection)];
}
