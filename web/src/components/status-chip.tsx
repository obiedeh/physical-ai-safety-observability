import type { CameraState, Severity } from "@/lib/api";
import { Chip, type ChipTone } from "./ui";

export function cameraStateTone(state: CameraState | string | null | undefined): ChipTone {
  switch (state) {
    case "streaming":
      return "ok";
    case "starting":
    case "connecting":
    case "reconnecting":
      return "warn";
    case "error":
      return "danger";
    case "ended":
      return "info";
    default:
      return "neutral";
  }
}

export function CameraStateChip({ state }: { state: CameraState | string | null | undefined }) {
  const tone = cameraStateTone(state);
  return (
    <Chip tone={tone}>
      {state === "streaming" && <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-ok" />}
      {state ?? "not running"}
    </Chip>
  );
}

export function severityTone(sev: Severity | string | null | undefined): ChipTone {
  switch (sev) {
    case "critical":
      return "danger";
    case "high":
      return "danger";
    case "medium":
      return "warn";
    case "low":
      return "info";
    default:
      return "neutral";
  }
}

export function SeverityChip({ severity }: { severity: Severity | string | null | undefined }) {
  return (
    <Chip tone={severityTone(severity)} className="uppercase">
      {severity ?? "—"}
    </Chip>
  );
}

export function ServerStateChip({ state }: { state: "stopped" | "starting" | "failed" | string }) {
  const tone: ChipTone = state === "starting" ? "warn" : state === "failed" ? "danger" : "neutral";
  return <Chip tone={tone}>{state}</Chip>;
}
