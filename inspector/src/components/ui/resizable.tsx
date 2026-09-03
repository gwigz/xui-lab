"use client";

import { GripVerticalIcon } from "lucide-react";
import type { ComponentProps, ReactElement } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { cn } from "@/lib/utils";

export function ResizablePanelGroup({
  className,
  ...props
}: ComponentProps<typeof Group>): ReactElement {
  return (
    <Group
      className={cn("flex h-full w-full aria-[orientation=vertical]:flex-col", className)}
      data-slot="resizable-panel-group"
      {...props}
    />
  );
}

export function ResizablePanel(props: ComponentProps<typeof Panel>): ReactElement {
  return <Panel data-slot="resizable-panel" {...props} />;
}

export function ResizableHandle({
  withHandle,
  className,
  ...props
}: ComponentProps<typeof Separator> & {
  withHandle?: boolean | undefined;
}): ReactElement {
  return (
    <Separator
      className={cn(
        "relative flex w-px items-center justify-center bg-border after:absolute after:inset-y-0 after:left-1/2 after:w-1 after:-translate-x-1/2 focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-offset-1 aria-[orientation=horizontal]:h-px aria-[orientation=horizontal]:w-full aria-[orientation=horizontal]:after:top-1/2 aria-[orientation=horizontal]:after:left-0 aria-[orientation=horizontal]:after:h-1 aria-[orientation=horizontal]:after:w-full aria-[orientation=horizontal]:after:translate-x-0 aria-[orientation=horizontal]:after:-translate-y-1/2 [&[aria-orientation=horizontal]>div]:rotate-90",
        className,
      )}
      data-slot="resizable-handle"
      {...props}
    >
      {withHandle === true ? (
        <div className="z-10 flex h-4 w-3 items-center justify-center rounded-xs border bg-border">
          <GripVerticalIcon className="size-2.5" />
        </div>
      ) : null}
    </Separator>
  );
}

export { useDefaultLayout } from "react-resizable-panels";
