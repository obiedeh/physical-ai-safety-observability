import type { SourceKind } from "@/lib/api";
import { Chip, type ChipTone } from "./ui";

/**
 * Where the frames behind a camera, event, live result or run came from.
 * Live kinds are green; uploaded and synthetic footage is visibly different
 * so recorded or generated evidence is never read as a live camera.
 */
const LABEL: Record<SourceKind, string> = {
  live_rtsp: "live",
  usb: "usb live",
  browser: "browser live",
  uploaded_recorded: "uploaded · recorded",
  uploaded_generated: "uploaded · generated",
  synthetic: "synthetic",
};

const TIP: Record<SourceKind, string> = {
  live_rtsp: "Live network camera (RTSP, RTSPS or HTTP MJPEG).",
  usb: "Live USB camera attached to this device.",
  browser: "Live camera shared from an operator's browser.",
  uploaded_recorded: "Uploaded recording of a real scene. Not a live camera.",
  uploaded_generated: "Uploaded generated footage (simulation, text-to-video). Not a live camera.",
  synthetic: "Built-in synthetic test pattern. Not a live camera.",
};

const TONE: Record<SourceKind, ChipTone> = {
  live_rtsp: "ok",
  usb: "ok",
  browser: "ok",
  uploaded_recorded: "info",
  uploaded_generated: "warn",
  synthetic: "warn",
};

export function isLiveSource(kind: SourceKind | null | undefined): boolean {
  return kind === "live_rtsp" || kind === "usb" || kind === "browser";
}

export function SourceKindBadge({ kind, className }: { kind: SourceKind | null | undefined; className?: string }) {
  if (!kind || !(kind in LABEL)) return null;
  return (
    <Chip tone={TONE[kind]} title={TIP[kind]} className={className}>
      {LABEL[kind]}
    </Chip>
  );
}

/** Sentence shown next to evidence from non-live sources. */
export function evidenceNote(kind: SourceKind | null | undefined): string | null {
  if (!kind || isLiveSource(kind)) return null;
  return TIP[kind];
}
