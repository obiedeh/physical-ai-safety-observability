import type { CameraTestResult, ProbeStage } from "@/lib/api";
import { fmtNum } from "@/lib/utils";
import { Chip, Notice } from "./ui";

const STAGE_HELP: Record<ProbeStage, string> = {
  reachability: "Host/port not reachable. Check the address, VLAN, and that RTSP is enabled on the camera.",
  auth: "Authentication rejected. Check username/password (Tapo needs a camera account, not the cloud login).",
  path: "Stream path not found. Try the other quality or edit the path to match the camera firmware.",
  codec: "Stream opened but the codec is not decodable. Switch the camera to H.264.",
  timeout: "Timed out waiting for frames. Try TCP transport or the sub stream.",
  decode: "Frames arrived but could not be decoded.",
  url: "The URL could not be built from these settings.",
  ok: "Stream probed successfully.",
};

export function TestResultView({ result }: { result: CameraTestResult }) {
  if (result.ok) {
    return (
      <Notice kind="ok" className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <Chip tone="ok">ok</Chip>
          <span>{result.note ?? STAGE_HELP.ok}</span>
        </div>
        {(result.width || result.codec || result.fps != null) && (
          <div className="text-xs text-ok/90 flex gap-4 flex-wrap tabular-nums">
            {result.width && result.height && <span>{result.width}×{result.height}</span>}
            {result.codec && <span>{result.codec}</span>}
            {result.fps != null && <span>{fmtNum(result.fps)} fps</span>}
            {result.open_ms != null && <span>opened in {Math.round(result.open_ms)} ms</span>}
          </div>
        )}
        {result.masked_url && <div className="mono text-ok/80 break-all">{result.masked_url}</div>}
        {result.thumbnail_data_url && (
          <img src={result.thumbnail_data_url} alt="probe thumbnail" className="rounded-md border border-ok/30 max-h-48" />
        )}
      </Notice>
    );
  }
  return (
    <Notice kind="error" className="space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <Chip tone="danger">{result.stage}</Chip>
        <span>{STAGE_HELP[result.stage] ?? "Probe failed."}</span>
      </div>
      {result.error && <div className="mono text-destructive/90 break-all">{result.error}</div>}
      {result.masked_url && <div className="mono text-destructive/70 break-all">{result.masked_url}</div>}
    </Notice>
  );
}
