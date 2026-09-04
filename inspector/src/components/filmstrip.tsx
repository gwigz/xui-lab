import {
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from "react";
import type { FilmstripEntry } from "../contracts";
import {
  captureIndexAt,
  FILMSTRIP_FRAME_MARGIN,
  FILMSTRIP_TILE_AREA,
  filmstripTiles,
  inscribe,
  playheadPercent,
} from "../filmstrip-geometry";

export type FilmstripVersion = number | "live";

type FilmstripProps = Readonly<{
  captures: readonly FilmstripEntry[];
  version: FilmstripVersion;
  onVersion: (version: FilmstripVersion) => void;
  frameWidth: number;
  frameHeight: number;
}>;

type PreviewPoint = Readonly<{
  x: number;
  index: number;
}>;

function useWidth<T extends HTMLElement>(): readonly [RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (node === null) {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry !== undefined) {
        setWidth(entry.contentRect.width);
      }
    });
    observer.observe(node);
    setWidth(node.getBoundingClientRect().width);
    return () => {
      observer.disconnect();
    };
  }, []);

  return [ref, width];
}

function selectCapture(
  captures: readonly FilmstripEntry[],
  index: number,
  onVersion: (version: FilmstripVersion) => void,
): void {
  const last = captures.length - 1;
  const entry = captures[index];
  if (entry === undefined) {
    return;
  }
  onVersion(index >= last ? "live" : entry.version);
}

export function Filmstrip({
  captures,
  version,
  onVersion,
  frameWidth,
  frameHeight,
}: FilmstripProps) {
  const [laneRef, width] = useWidth<HTMLDivElement>();
  const dragging = useRef(false);
  const [preview, setPreview] = useState<PreviewPoint | undefined>();

  if (captures.length === 0) {
    return null;
  }

  const selectedIndex =
    version === "live"
      ? captures.length - 1
      : Math.max(
          0,
          captures.findIndex((entry) => entry.version === version),
        );
  const selected = captures[selectedIndex];
  const object = {
    width: frameWidth > 0 ? frameWidth : 16,
    height: frameHeight > 0 ? frameHeight : 10,
  };
  const frameSize = inscribe(object, FILMSTRIP_TILE_AREA);
  const tiles = filmstripTiles(captures.length, width, frameSize.width, FILMSTRIP_FRAME_MARGIN);
  const hoverSize = inscribe(object, { width: 320, height: 200 });
  const playhead = playheadPercent(selectedIndex, captures.length);
  const previewEntry = preview === undefined ? undefined : captures[preview.index];

  function indexFromClientX(clientX: number): number {
    const node = laneRef.current;
    if (node === null) {
      return selectedIndex;
    }
    const bounds = node.getBoundingClientRect();
    return captureIndexAt(clientX - bounds.left, bounds.width, captures.length);
  }

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>): void {
    if (event.button !== 0) {
      return;
    }
    dragging.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    setPreview(undefined);
    selectCapture(captures, indexFromClientX(event.clientX), onVersion);
  }

  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>): void {
    const index = indexFromClientX(event.clientX);
    const node = laneRef.current;
    const x = node === null ? 0 : event.clientX - node.getBoundingClientRect().left;
    if (dragging.current) {
      selectCapture(captures, index, onVersion);
      return;
    }
    setPreview({ x, index });
  }

  function onPointerUp(event: ReactPointerEvent<HTMLDivElement>): void {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    dragging.current = false;
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>): void {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      selectCapture(captures, Math.max(0, selectedIndex - 1), onVersion);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      selectCapture(captures, Math.min(captures.length - 1, selectedIndex + 1), onVersion);
    } else if (event.key === "Home") {
      event.preventDefault();
      selectCapture(captures, 0, onVersion);
    } else if (event.key === "End") {
      event.preventDefault();
      onVersion("live");
    }
  }

  function onWheel(event: ReactWheelEvent<HTMLDivElement>): void {
    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
    if (delta === 0) {
      return;
    }
    event.preventDefault();
    selectCapture(
      captures,
      Math.min(captures.length - 1, Math.max(0, selectedIndex + Math.sign(delta))),
      onVersion,
    );
  }

  return (
    <div
      aria-label="Capture timeline"
      aria-valuemax={captures.length}
      aria-valuemin={1}
      aria-valuenow={selectedIndex + 1}
      aria-valuetext={selected?.label}
      className="relative min-w-0 cursor-text select-none border-white/8 border-t bg-black/40 px-1 pt-3 pb-1"
      onDoubleClick={() => onVersion("live")}
      onKeyDown={onKeyDown}
      onPointerCancel={onPointerUp}
      onPointerDown={onPointerDown}
      onPointerLeave={() => {
        dragging.current = false;
        setPreview(undefined);
      }}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onWheel={onWheel}
      role="slider"
      tabIndex={0}
    >
      <div className="relative mb-1 h-2">
        {captures.length <= 200
          ? captures.map((entry, index) => (
              <span
                className="absolute top-0.5 h-1 w-px bg-white/25"
                key={entry.version}
                style={{ left: `${playheadPercent(index, captures.length).toFixed(3)}%` }}
              />
            ))
          : null}
        <span
          className="absolute top-0 z-[1] h-2 w-2 -translate-x-1/2 rounded-full bg-sky-400"
          style={{ left: `${playhead.toFixed(3)}%` }}
        />
      </div>
      <div
        className="relative overflow-hidden"
        ref={laneRef}
        style={{ height: frameSize.height + 2 * FILMSTRIP_FRAME_MARGIN }}
      >
        {tiles.map((captureIndex, tileIndex) => {
          const entry = captures[captureIndex];
          if (entry === undefined) {
            return null;
          }
          const pitch = width / tiles.length;
          const left = tileIndex * pitch + Math.max(0, (pitch - frameSize.width) / 2);
          return (
            <div
              className="pointer-events-none absolute overflow-hidden bg-black shadow-[0_0_0_1px_rgba(255,255,255,0.08)]"
              key={`${String(entry.version)}-${String(tileIndex)}`}
              style={{
                left,
                top: FILMSTRIP_FRAME_MARGIN,
                width: frameSize.width,
                height: frameSize.height,
              }}
            >
              <img
                alt=""
                className="size-full object-cover"
                draggable={false}
                src={`/api/v1/captures/${String(entry.version)}`}
              />
            </div>
          );
        })}
        <div
          className="pointer-events-none absolute inset-y-0 z-[1] w-0.5 bg-sky-400"
          style={{ left: `${playhead.toFixed(3)}%` }}
        />
        {preview === undefined ? null : (
          <div
            className="pointer-events-none absolute inset-y-0 z-[2] w-px bg-white/70"
            style={{ left: preview.x }}
          />
        )}
      </div>
      {selected === undefined ? null : (
        <div className="flex min-w-0 items-center justify-between gap-3 px-1 pt-1 font-mono text-[10px] text-neutral-400">
          <span className="truncate" title={selected.label}>
            {selected.label}
          </span>
          <span className="shrink-0 text-neutral-500">{selected.action ?? selected.name}</span>
        </div>
      )}
      {previewEntry === undefined || preview === undefined ? null : (
        <div
          className="pointer-events-none absolute z-20 overflow-hidden rounded-md border border-white/15 bg-neutral-950 shadow-[0_8px_24px_rgba(0,0,0,0.55)]"
          style={{
            bottom: "100%",
            left: Math.max(8, Math.min(preview.x, Math.max(8, width - hoverSize.width - 8))),
            width: hoverSize.width,
            marginBottom: 8,
          }}
        >
          <img
            alt=""
            className="block w-full bg-black object-contain"
            draggable={false}
            height={hoverSize.height}
            src={`/api/v1/captures/${String(previewEntry.version)}`}
            width={hoverSize.width}
          />
          <div className="px-2 py-1 font-mono text-[11px]">
            <div className="truncate text-neutral-300">{previewEntry.label}</div>
            <div className="truncate text-neutral-500">
              {previewEntry.action ?? previewEntry.name}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
