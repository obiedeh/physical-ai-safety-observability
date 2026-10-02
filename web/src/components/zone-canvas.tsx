import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plus, RotateCcw, Trash2 } from "lucide-react";
import type { Zone } from "@/lib/api";
import { api } from "@/lib/api";
import { useElementSize } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { Button, Input, Select } from "./ui";

const ZONE_TYPES = ["restricted", "emergency_path", "robot_cell", "walkway", "other"];

/**
 * Polygon zone editor. Draws over the camera snapshot (saved cameras) or an
 * empty 16:9 canvas (new cameras). Click adds a vertex to the selected zone;
 * Backspace or right-click removes the last one. Coordinates are stored
 * normalized 0..1 so the worker can scale them to any frame size.
 */
export function ZoneCanvas({
  zones,
  onChange,
  cameraId,
  snapshotAvailable = true,
}: {
  zones: Zone[];
  onChange: (zones: Zone[]) => void;
  cameraId?: string | null;
  snapshotAvailable?: boolean;
}) {
  const { ref, size } = useElementSize<HTMLDivElement>();
  const [selected, setSelected] = useState<number>(zones.length ? 0 : -1);
  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null);
  const [snapshotFailed, setSnapshotFailed] = useState(false);
  const [aspect, setAspect] = useState(16 / 9);
  const [hover, setHover] = useState<[number, number] | null>(null);
  const focusRef = useRef<HTMLDivElement | null>(null);

  const refreshSnapshot = useCallback(() => {
    if (!cameraId || !snapshotAvailable) {
      setSnapshotUrl(null);
      return;
    }
    setSnapshotFailed(false);
    setSnapshotUrl(api.stream.snapshotUrl(cameraId));
  }, [cameraId, snapshotAvailable]);

  useEffect(() => {
    refreshSnapshot();
  }, [refreshSnapshot]);

  useEffect(() => {
    if (selected >= zones.length) setSelected(zones.length - 1);
  }, [zones.length, selected]);

  const width = size.width;
  const height = width / aspect;

  const toNorm = (e: React.MouseEvent<HTMLDivElement>): [number, number] => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    return [round4(x), round4(y)];
  };

  const updateZone = (idx: number, patch: Partial<Zone>) => {
    onChange(zones.map((z, i) => (i === idx ? { ...z, ...patch } : z)));
  };

  const addVertex = (pt: [number, number]) => {
    if (selected < 0 || selected >= zones.length) return;
    updateZone(selected, { polygon: [...zones[selected].polygon, pt] });
  };

  const removeLastVertex = () => {
    if (selected < 0 || selected >= zones.length) return;
    const poly = zones[selected].polygon;
    if (!poly.length) return;
    updateZone(selected, { polygon: poly.slice(0, -1) });
  };

  const addZone = () => {
    const n = zones.length + 1;
    let id = `zone-${n}`;
    while (zones.some((z) => z.zone_id === id)) id = `zone-${n + Math.floor(Math.random() * 1000)}`;
    onChange([...zones, { zone_id: id, type: "restricted", polygon: [] }]);
    setSelected(zones.length);
    focusRef.current?.focus();
  };

  const removeZone = (idx: number) => {
    onChange(zones.filter((_, i) => i !== idx));
    setSelected((s) => (s === idx ? Math.min(idx, zones.length - 2) : s > idx ? s - 1 : s));
  };

  const invalid = useMemo(() => zones.filter((z) => z.polygon.length < 3).map((z) => z.zone_id), [zones]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-xs text-muted-foreground">
          Select a zone, click on the frame to add vertices. <kbd className="mono">Backspace</kbd> or
          right-click removes the last vertex. At least 3 vertices per zone.
        </p>
        <div className="flex gap-2">
          {cameraId && snapshotAvailable && (
            <Button size="sm" variant="ghost" onClick={refreshSnapshot} title="Reload snapshot">
              <RotateCcw className="h-3.5 w-3.5" /> Snapshot
            </Button>
          )}
          <Button size="sm" onClick={addZone}>
            <Plus className="h-3.5 w-3.5" /> Add zone
          </Button>
        </div>
      </div>

      <div
        ref={(el) => {
          ref.current = el;
          focusRef.current = el;
        }}
        tabIndex={0}
        role="application"
        aria-label="Zone editor"
        className={cn(
          "relative w-full select-none bg-black rounded-md overflow-hidden border border-border outline-none",
          selected >= 0 ? "cursor-crosshair focus:ring-2 focus:ring-ring/60" : "cursor-not-allowed"
        )}
        style={{ height: height > 0 ? height : undefined, aspectRatio: height > 0 ? undefined : `${aspect}` }}
        onClick={(e) => {
          if (selected < 0) return;
          addVertex(toNorm(e));
          e.currentTarget.focus();
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          removeLastVertex();
        }}
        onMouseMove={(e) => setHover(toNorm(e))}
        onMouseLeave={() => setHover(null)}
        onKeyDown={(e) => {
          if (e.key === "Backspace" || e.key === "Delete") {
            e.preventDefault();
            removeLastVertex();
          }
        }}
      >
        {snapshotUrl && !snapshotFailed ? (
          <img
            src={snapshotUrl}
            alt=""
            className="absolute inset-0 w-full h-full object-fill opacity-90"
            draggable={false}
            onLoad={(e) => {
              const img = e.currentTarget;
              if (img.naturalWidth && img.naturalHeight) setAspect(img.naturalWidth / img.naturalHeight);
            }}
            onError={() => setSnapshotFailed(true)}
          />
        ) : (
          <div className="absolute inset-0 grid place-items-center text-xs text-muted-foreground bg-[linear-gradient(45deg,hsl(222_40%_14%)_25%,transparent_25%,transparent_75%,hsl(222_40%_14%)_75%),linear-gradient(45deg,hsl(222_40%_14%)_25%,transparent_25%,transparent_75%,hsl(222_40%_14%)_75%)] bg-[length:24px_24px] bg-[position:0_0,12px_12px]">
            {cameraId && snapshotAvailable
              ? "No snapshot yet (camera not streaming). Drawing on a 16:9 canvas."
              : "Save the camera to draw over a live snapshot. Drawing on a 16:9 canvas."}
          </div>
        )}
        {width > 0 && (
          <svg className="absolute inset-0 pointer-events-none" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
            {zones.map((z, i) => {
              const sel = i === selected;
              const pts = z.polygon;
              const color = sel ? "hsl(199 95% 60%)" : "hsl(38 95% 58%)";
              const preview = sel && hover && pts.length ? [...pts, hover] : pts;
              return (
                <g key={z.zone_id}>
                  {preview.length >= 2 && (
                    <polyline
                      points={preview.map(([x, y]) => `${x * width},${y * height}`).join(" ")}
                      fill={preview.length >= 3 ? `${color.slice(0, -1)} / 0.12)` : "none"}
                      stroke={color}
                      strokeWidth={sel ? 2 : 1.5}
                      strokeDasharray={sel ? undefined : "6 4"}
                    />
                  )}
                  {pts.length >= 3 && (
                    <line
                      x1={pts[pts.length - 1][0] * width}
                      y1={pts[pts.length - 1][1] * height}
                      x2={pts[0][0] * width}
                      y2={pts[0][1] * height}
                      stroke={color}
                      strokeWidth={1}
                      strokeDasharray="3 3"
                      opacity={0.7}
                    />
                  )}
                  {pts.map(([x, y], j) => (
                    <circle key={j} cx={x * width} cy={y * height} r={sel ? 4 : 3} fill={color} stroke="#000" strokeWidth={1} />
                  ))}
                  {pts.length > 0 && (
                    <text x={pts[0][0] * width + 6} y={pts[0][1] * height - 6} fontSize={11} fill={color} fontFamily="ui-monospace, monospace">
                      {z.zone_id}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        )}
        {hover && selected >= 0 && (
          <div className="absolute bottom-1 right-2 mono text-muted-foreground bg-background/70 px-1 rounded">
            {hover[0].toFixed(3)}, {hover[1].toFixed(3)}
          </div>
        )}
      </div>

      {zones.length === 0 ? (
        <p className="text-xs text-muted-foreground">No zones. Zones are optional; RESTRICTED_ZONE_ENTRY needs at least one.</p>
      ) : (
        <ul className="space-y-2">
          {zones.map((z, i) => (
            <li
              key={i}
              className={cn(
                "card p-2 flex flex-wrap items-center gap-2",
                i === selected && "ring-1 ring-primary/60"
              )}
              onClick={() => setSelected(i)}
            >
              <input
                type="radio"
                name="zone-select"
                checked={i === selected}
                onChange={() => setSelected(i)}
                aria-label={`select ${z.zone_id}`}
              />
              <Input
                className="w-36"
                value={z.zone_id}
                onChange={(e) => updateZone(i, { zone_id: e.target.value })}
                placeholder="zone id"
              />
              <Select className="w-40" value={z.type} onChange={(e) => updateZone(i, { type: e.target.value })}>
                {[...new Set([...ZONE_TYPES, z.type])].map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
              <span className={cn("text-xs", z.polygon.length < 3 ? "text-warn" : "text-muted-foreground")}>
                {z.polygon.length} vertices
              </span>
              <details className="text-xs text-muted-foreground">
                <summary className="cursor-pointer">coordinates</summary>
                <textarea
                  className="mt-1 w-full min-w-[16rem] mono"
                  rows={3}
                  value={z.polygon.map((p) => `${p[0]},${p[1]}`).join("\n")}
                  onChange={(e) => {
                    const poly = e.target.value
                      .split(/\n/)
                      .map((l) => l.trim())
                      .filter(Boolean)
                      .map((l) => l.split(/[,\s]+/).map(Number))
                      .filter((p) => p.length >= 2 && p.every((v) => Number.isFinite(v)))
                      .map((p) => [clamp01(p[0]), clamp01(p[1])]);
                    updateZone(i, { polygon: poly });
                  }}
                />
              </details>
              <div className="ml-auto flex gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={(e) => {
                    e.stopPropagation();
                    updateZone(i, { polygon: [] });
                  }}
                  title="Clear vertices"
                >
                  Clear
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeZone(i);
                  }}
                  title="Remove zone"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {invalid.length > 0 && (
        <p className="text-xs text-warn">
          Zones with fewer than 3 vertices cannot be saved: {invalid.join(", ")}.
        </p>
      )}
    </div>
  );
}

const round4 = (v: number) => Math.round(v * 10000) / 10000;
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
