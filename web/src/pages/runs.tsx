import { useMemo, useState } from "react";
import { Circle, Square } from "lucide-react";
import { api, apiErrorMessage, type RunSummary } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { fmtDuration, fmtMs, fmtNum, fmtTime } from "@/lib/utils";
import { Button, Card, Chip, Empty, Field, Input, Notice, Select, Stat } from "@/components/ui";
import { SourceKindBadge } from "@/components/source-kind-badge";

export function RunsPage() {
  const status = usePoll(() => api.runs.status(), 2000);
  const runs = usePoll(() => api.runs.list(), 10000);
  const runtime = usePoll(() => api.runtime.status(), 5000);

  const runningCams = useMemo(() => runtime.data?.cameras ?? [], [runtime.data]);
  const [cameraId, setCameraId] = useState("");
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const effectiveCamera = cameraId || runningCams[0]?.camera_id || "";
  const rec = status.data;

  const start = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.runs.start({ camera_id: effectiveCamera, name: name.trim(), notes: notes.trim() });
      setMsg({ kind: "ok", text: "Recording started." });
      await status.refresh();
    } catch (e) {
      setMsg({ kind: "error", text: apiErrorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.runs.stop();
      setMsg({ kind: "ok", text: `Run written to ${res.written} (${res.frames} frames).` });
      await status.refresh();
      await runs.refresh();
    } catch (e) {
      setMsg({ kind: "error", text: apiErrorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  const sorted = useMemo(
    () => [...(runs.data ?? [])].sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? "")),
    [runs.data]
  );

  return (
    <div className="space-y-4">
      <Card
        title={
          <span className="flex items-center gap-2">
            Measured run
            {rec?.recording ? <Chip tone="danger"><Circle className="h-2 w-2 fill-current" /> recording</Chip> : <Chip tone="neutral">idle</Chip>}
          </span>
        }
      >
        {status.error && <Notice kind="error">{status.error}</Notice>}
        {rec?.recording ? (
          <div className="space-y-3">
            <div className="grid gap-4 grid-cols-2 sm:grid-cols-5">
              <Stat label="Name" value={rec.name} />
              <Stat label="Camera" value={runningCams.find((c) => c.camera_id === rec.camera_id)?.name ?? rec.camera_id} sub={rec.camera_id} />
              <Stat label="Elapsed" value={fmtDuration(rec.elapsed_s)} />
              <Stat label="Frames" value={rec.frames ?? 0} sub="inferred frames" />
              <Stat label="Events" value={rec.events ?? 0} />
            </div>
            <Button variant="danger" busy={busy} onClick={() => void stop()}>
              <Square className="h-3.5 w-3.5" /> Stop and write report
            </Button>
          </div>
        ) : (
          <form
            className="grid gap-3 sm:grid-cols-[14rem_1fr_1fr_auto] items-end"
            onSubmit={(e) => {
              e.preventDefault();
              void start();
            }}
          >
            <Field label="Camera" hint={runningCams.length ? undefined : "No camera is running."}>
              <Select value={effectiveCamera} onChange={(e) => setCameraId(e.target.value)} disabled={!runningCams.length}>
                {runningCams.map((c) => (
                  <option key={c.camera_id} value={c.camera_id}>
                    {c.name} ({c.state})
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Name">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="thor-2b-constrained-60f" required maxLength={80} />
            </Field>
            <Field label="Notes">
              <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="optional" />
            </Field>
            <Button type="submit" variant="primary" busy={busy} disabled={!effectiveCamera || !name.trim()}>
              <Circle className="h-3.5 w-3.5" /> Start
            </Button>
          </form>
        )}
        {msg && <Notice kind={msg.kind} className="mt-3 break-all">{msg.text}</Notice>}
        <p className="mt-3 text-xs text-muted-foreground">
          A run records every inferred frame, its latency and the events it produced, then writes a <span className="mono">run-report-v1</span> JSON artifact under the reports directory. One run at a time.
        </p>
      </Card>

      <Card title={<span>Runs <span className="text-muted-foreground font-normal">({sorted.length})</span></span>} bodyClassName="p-0">
        {runs.error && <Notice kind="error" className="m-3">{runs.error}</Notice>}
        {!runs.loading && sorted.length === 0 ? (
          <div className="p-4">
            <Empty>No run reports found.</Empty>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs uppercase tracking-wide text-muted-foreground border-b border-border">
                <tr>
                  <th className="text-left px-3 py-2">Name</th>
                  <th className="text-left px-3 py-2">Host</th>
                  <th className="text-left px-3 py-2">Started</th>
                  <th className="text-left px-3 py-2">Status</th>
                  <th className="text-right px-3 py-2">Frames</th>
                  <th className="text-right px-3 py-2" title="Processed (inferred) frames per second, not camera fps">
                    fps*
                  </th>
                  <th className="text-left px-3 py-2">Model</th>
                  <th className="text-right px-3 py-2">Events</th>
                  <th className="text-right px-3 py-2">Inference p50</th>
                  <th className="text-left px-3 py-2">Artifact</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {sorted.map((r) => (
                  <RunRow key={r.path} r={r} />
                ))}
              </tbody>
            </table>
            <p className="px-3 py-2 text-xs text-muted-foreground border-t border-border">
              * fps is processed (inferred) frames per second over the run, not the camera frame rate.
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}

function RunRow({ r }: { r: RunSummary }) {
  const tone =
    r.status === "complete" || r.status === "completed" || r.status === "ok"
      ? "ok"
      : r.status === "failed"
        ? "danger"
        : "neutral";
  return (
    <tr className="hover:bg-secondary/30">
      <td className="px-3 py-2 font-medium whitespace-nowrap"><span className="flex items-center gap-2">{r.name}<SourceKindBadge kind={r.source_kind} /></span></td>
      <td className="px-3 py-2 text-muted-foreground">{r.host}</td>
      <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{fmtTime(r.started_at)}</td>
      <td className="px-3 py-2"><Chip tone={tone}>{r.status ?? "—"}</Chip></td>
      <td className="px-3 py-2 text-right tabular-nums">{r.frames ?? "—"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{fmtNum(r.fps, 2)}</td>
      <td className="px-3 py-2 mono text-muted-foreground max-w-[14rem] truncate" title={r.model ?? ""}>{r.model ?? "—"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{r.events ?? "—"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{fmtMs(r.inference_p50_ms)}</td>
      <td className="px-3 py-2 mono text-muted-foreground max-w-[22rem] truncate" title={r.path}>{r.path}</td>
    </tr>
  );
}
