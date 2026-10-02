import type { Detection, InferenceResult, Zone } from "@/lib/api";

/**
 * SVG overlay drawn in normalized coordinates (viewBox 0 0 1 1, non-uniform
 * scaling) so bboxes land on the rendered video regardless of its pixel size.
 * Text is drawn in a separate pixel-space layer so it does not stretch.
 */
export function DetectionOverlay({
  result,
  zones = [],
  width,
  height,
}: {
  result: InferenceResult | null;
  zones?: Zone[];
  width: number;
  height: number;
}) {
  const detections = result?.detections ?? [];
  const hasEvents = (result?.events?.length ?? 0) > 0;
  if (width <= 0 || height <= 0) return null;

  return (
    <svg
      className="absolute inset-0 pointer-events-none"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
    >
      {zones.map((z) =>
        z.polygon.length >= 3 ? (
          <polygon
            key={z.zone_id}
            points={z.polygon.map(([x, y]) => `${x * width},${y * height}`).join(" ")}
            fill="hsl(38 95% 58% / 0.08)"
            stroke="hsl(38 95% 58% / 0.8)"
            strokeWidth={1.5}
            strokeDasharray="6 4"
          />
        ) : null
      )}
      {zones.map((z) => {
        if (z.polygon.length < 1) return null;
        const [x, y] = z.polygon[0];
        return (
          <text
            key={`${z.zone_id}-label`}
            x={x * width + 4}
            y={y * height + 12}
            fontSize={11}
            fill="hsl(38 95% 58%)"
            fontFamily="ui-monospace, monospace"
          >
            {z.zone_id} ({z.type})
          </text>
        );
      })}
      {detections.map((d, i) => (
        <DetectionBox key={i} d={d} width={width} height={height} hasEvents={hasEvents} />
      ))}
    </svg>
  );
}

function DetectionBox({
  d,
  width,
  height,
  hasEvents,
}: {
  d: Detection;
  width: number;
  height: number;
  hasEvents: boolean;
}) {
  if (!d.bbox) return null;
  const [nx, ny, nw, nh] = d.bbox;
  const x = nx * width;
  const y = ny * height;
  const w = Math.max(1, nw * width);
  const h = Math.max(1, nh * height);
  const ppeMissing = d.ppe != null && (d.ppe.hard_hat === false || d.ppe.vest === false);
  const blocking = d.blocking_emergency_path === true;
  const alert = ppeMissing || blocking;
  const stroke = alert
    ? "hsl(0 80% 60%)"
    : hasEvents
      ? "hsl(38 95% 58%)"
      : "hsl(152 65% 48%)";
  const conf = typeof d.confidence === "number" ? ` ${Math.round(d.confidence * 100)}%` : "";
  const ppe =
    d.ppe != null
      ? ` · hat:${flag(d.ppe.hard_hat)} vest:${flag(d.ppe.vest)}`
      : "";
  const label = `${d.label ?? "object"}${conf}${ppe}${blocking ? " · blocking path" : ""}`;
  const labelY = y > 16 ? y - 4 : y + h + 12;
  const approxW = label.length * 6.4 + 8;

  return (
    <g>
      {hasEvents && (
        <rect
          x={x - 2}
          y={y - 2}
          width={w + 4}
          height={h + 4}
          fill="none"
          stroke={stroke}
          strokeOpacity={0.35}
          strokeWidth={6}
          rx={3}
        />
      )}
      <rect x={x} y={y} width={w} height={h} fill={stroke} fillOpacity={0.06} stroke={stroke} strokeWidth={2} rx={2} />
      <rect
        x={x}
        y={labelY - 11}
        width={Math.min(approxW, Math.max(60, width - x))}
        height={14}
        fill="hsl(222 47% 9% / 0.85)"
        rx={2}
      />
      <text x={x + 4} y={labelY} fontSize={11} fill={stroke} fontFamily="ui-monospace, monospace">
        {label}
      </text>
    </g>
  );
}

function flag(v: boolean | null | undefined): string {
  if (v === true) return "✓";
  if (v === false) return "✗";
  return "?";
}
