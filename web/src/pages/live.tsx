import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, Play, Radio, RotateCcw, WifiOff } from "lucide-react";
import { api, type Camera, type InferenceResult, type RuntimeStatus, type SafetyEvent } from "@/lib/api";
import { useElementSize, useLiveResults, usePoll } from "@/lib/hooks";
import { cn, fmtClock, fmtMs, fmtNum, fmtPct, ruleLabel } from "@/lib/utils";
import { Button, Card, Chip, Empty, Stat } from "@/components/ui";
import { CameraStateChip, SeverityChip } from "@/components/status-chip";
import { SourceKindBadge, evidenceNote } from "@/components/source-kind-badge";
import { DetectionOverlay } from "@/components/detection-overlay";
import { useWebcamPush, WebcamControls } from "@/components/webcam-push";

export function LivePage() {
  const [params, setParams] = useSearchParams();
  const cameras = usePoll(() => api.cameras.list(), 5000);
  const runtime = usePoll(() => api.runtime.status(), 2000);
  const events = usePoll(() => api.events.list(), 3000);

  const enabled = useMemo(() => (cameras.data ?? []).filter((c) => c.enabled), [cameras.data]);
  const requested = params.get("camera");
  const selectedId = enabled.some((c) => c.camera_id === requested) ? requested : enabled[0]?.camera_id ?? null;
  const selected = enabled.find((c) => c.camera_id === selectedId) ?? null;

  useEffect(() => {
    if (selectedId && selectedId !== requested) setParams({ camera: selectedId }, { replace: true });
  }, [selectedId, requested, setParams]);

  const { results, state: sseState } = useLiveResults();
  const result = selectedId ? results[selectedId] ?? null : null;
  const runtimeCam = runtime.data?.cameras.find((c) => c.camera_id === selectedId) ?? null;
  const camEvents = useMemo(
    () => (events.data ?? []).filter((e) => !selectedId || e.camera_id === selectedId).slice(-40).reverse(),
    [events.data, selectedId]
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        {enabled.length === 0 && !cameras.loading && (
          <span className="text-sm text-muted-foreground">
            No enabled cameras. <Link to="/ui/cameras" className="text-primary underline underline-offset-2">Add one under Cameras</Link> or{" "}
            <Link to="/ui/cameras?action=upload" className="text-primary underline underline-offset-2">upload a video</Link> to play as a camera.
          </span>
        )}
        {enabled.map((c) => {
          const r = results[c.camera_id];
          const rt = runtime.data?.cameras.find((x) => x.camera_id === c.camera_id);
          const alert = (r?.events?.length ?? 0) > 0;
          return (
            <button
              key={c.camera_id}
              type="button"
              onClick={() => setParams({ camera: c.camera_id })}
              className={cn(
                "flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm transition-colors",
                c.camera_id === selectedId
                  ? "border-primary/60 bg-primary/10 text-foreground"
                  : "border-border bg-card text-muted-foreground hover:text-foreground"
              )}
            >
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  rt?.state === "streaming" ? "bg-ok live-dot" : rt?.state === "error" ? "bg-destructive" : "bg-muted-foreground/50"
                )}
              />
              {c.name}
              {alert && <AlertTriangle className="h-3.5 w-3.5 text-warn" />}
              <SourceKindBadge kind={c.source_kind} />
            </button>
          );
        })}
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
          {sseState === "open" ? <Radio className="h-3.5 w-3.5 text-ok" /> : <WifiOff className="h-3.5 w-3.5 text-warn" />}
          results {sseState}
        </span>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-4 min-w-0">
          {selected ? (
            <VideoPanel camera={selected} result={result} runtimeState={runtimeCam?.state ?? null} onReplayed={() => void runtime.refresh()} />
          ) : (
            <Empty>Select a camera to view its feed.</Empty>
          )}
          <StatusStrip runtime={runtime.data} runtimeError={runtime.error} cam={runtimeCam} result={result} />
        </div>

        <Card title="Recent events" className="min-w-0" bodyClassName="p-0 max-h-[70vh] overflow-y-auto">
          {events.error && <p className="p-3 text-xs text-destructive">{events.error}</p>}
          {camEvents.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No events for this camera yet.</p>
          ) : (
            <ul className="divide-y divide-border">
              {camEvents.map((e) => (
                <EventRow key={e.event_id} e={e} />
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function VideoPanel({ camera, result, runtimeState, onReplayed }: { camera: Camera; result: InferenceResult | null; runtimeState: string | null; onReplayed: () => void }) {
  const { ref, size } = useElementSize<HTMLDivElement>();
  const isBrowser = camera.profile === "browser_webrtc";
  const isClip = camera.connector === "upload";
  const ended = isClip && runtimeState === "ended";
  const [replaying, setReplaying] = useState(false);
  const [replayError, setReplayError] = useState<string | null>(null);

  /** Uploaded video: play the file again from its first frame and re-attach the stream. */
  const replay = async () => {
    setReplaying(true);
    setReplayError(null);
    try {
      await api.cameras.restart(camera.camera_id);
      setImgError(false);
      setMjpegUrl(`${api.stream.mjpegUrl(camera.camera_id)}?t=${Date.now()}`);
      onReplayed();
    } catch (e) {
      setReplayError(e instanceof Error ? e.message : "Could not start playback");
    } finally {
      setReplaying(false);
    }
  };
  const push = useWebcamPush(isBrowser ? camera.camera_id : null);
  const [imgError, setImgError] = useState(false);
  const [mjpegUrl, setMjpegUrl] = useState(() => api.stream.mjpegUrl(camera.camera_id));

  // Re-point the <img> when the camera changes; retry when the stream 404s
  // (camera starting) so the video returns without a reload.
  useEffect(() => {
    setImgError(false);
    setMjpegUrl(`${api.stream.mjpegUrl(camera.camera_id)}?t=${Date.now()}`);
  }, [camera.camera_id]);
  useEffect(() => {
    if (!imgError) return;
    const id = window.setTimeout(() => {
      setImgError(false);
      setMjpegUrl(`${api.stream.mjpegUrl(camera.camera_id)}?t=${Date.now()}`);
    }, 3000);
    return () => window.clearTimeout(id);
  }, [imgError, camera.camera_id]);

  // The video is object-contain inside a 16:9 box; map the overlay onto the
  // letterboxed content rect so normalized bboxes line up for any frame aspect.
  const boxW = size.width;
  const boxH = (size.width * 9) / 16;
  const frameAspect = result?.frame_size?.[0] && result.frame_size[1] ? result.frame_size[0] / result.frame_size[1] : 16 / 9;
  const contentW = frameAspect >= boxW / boxH ? boxW : boxH * frameAspect;
  const contentH = frameAspect >= boxW / boxH ? boxW / frameAspect : boxH;
  const offsetX = (boxW - contentW) / 2;
  const offsetY = (boxH - contentH) / 2;

  const feedback = result?.status === "ok" ? result.feedback ?? null : null;
  const feedbackTone = !feedback
    ? "neutral"
    : /no ppe/i.test(feedback)
      ? "danger"
      : /with ppe/i.test(feedback)
        ? "ok"
        : "neutral";

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          {camera.name}
          <SourceKindBadge kind={camera.source_kind} />
          <span className="mono text-muted-foreground">{camera.camera_id}</span>
        </span>
      }
      actions={
        <>
          {result?.model && <Chip tone="neutral" title="model">{result.model}</Chip>}
          {result?.status && result.status !== "ok" && <Chip tone="warn">{result.status}</Chip>}
        </>
      }
      bodyClassName="p-0"
    >
      {evidenceNote(camera.source_kind) && (
        <div className="px-4 py-1.5 border-b border-warn/40 bg-warn/10 text-xs text-warn flex items-center gap-2">
          <SourceKindBadge kind={camera.source_kind} /> {evidenceNote(camera.source_kind)} Events and evidence from this feed carry the same label.
        </div>
      )}
      <div ref={ref} className="relative bg-black aspect-video w-full overflow-hidden">
        {isBrowser && push.active ? (
          <video ref={push.videoRef} muted playsInline className="absolute inset-0 w-full h-full object-contain" />
        ) : (
          <img
            key={mjpegUrl}
            src={mjpegUrl}
            alt={`${camera.name} live`}
            className="absolute inset-0 w-full h-full object-contain"
            onError={() => setImgError(true)}
          />
        )}
        {imgError && !(isBrowser && push.active) && !ended && (
          <div className="absolute inset-0 grid place-items-center text-xs text-muted-foreground bg-background/60">
            Stream not available yet — retrying…
          </div>
        )}
        {ended && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-background/70">
            <Button variant="primary" busy={replaying} onClick={() => void replay()} title="Play the video again from the start">
              <Play className="h-4 w-4" /> Play again
            </Button>
            <span className="text-xs text-muted-foreground">Clip finished. Set Playback to "loop" on the Cameras page to repeat automatically.</span>
            {replayError && <span className="text-xs text-destructive">{replayError}</span>}
          </div>
        )}
        {isClip && !ended && (
          <div className="absolute top-2 right-2 z-10">
            <Button size="sm" busy={replaying} onClick={() => void replay()} title="Play the video again from the start">
              <RotateCcw className="h-3.5 w-3.5" /> Replay
            </Button>
          </div>
        )}
        <div className="absolute" style={{ left: offsetX, top: offsetY, width: contentW, height: contentH }}>
          <DetectionOverlay result={result} zones={camera.zones} width={contentW} height={contentH} />
        </div>
        {feedback && (
          <div
            className={cn(
              "absolute top-2 left-2 rounded-md px-2.5 py-1 text-sm font-semibold shadow",
              feedbackTone === "danger" && "bg-destructive text-destructive-foreground",
              feedbackTone === "ok" && "bg-ok text-primary-foreground",
              feedbackTone === "neutral" && "bg-background/80 text-foreground border border-border"
            )}
          >
            {feedback}
          </div>
        )}
        {result && (
          <div className="absolute bottom-2 right-2 mono text-muted-foreground bg-background/70 px-1.5 py-0.5 rounded">
            {fmtClock(result.timestamp)} · {result.detections.length} det
            {result.frame_size ? ` · ${result.frame_size[0]}×${result.frame_size[1]}` : ""}
          </div>
        )}
      </div>
      {isBrowser && (
        <div className="px-4 py-2 border-t border-border">
          <WebcamControls push={push} />
        </div>
      )}
      {result && result.events.length > 0 && (
        <ul className="px-4 py-2 border-t border-border space-y-1">
          {result.events.map((e) => (
            <li key={e.event_id} className="flex items-center gap-2 text-sm">
              <SeverityChip severity={e.severity} />
              <span className="font-medium">{ruleLabel(e.rule_id)}</span>
              <span className="text-muted-foreground truncate">{e.summary}</span>
              {e.human_review_required && <Chip tone="warn">review</Chip>}
            </li>
          ))}
        </ul>
      )}
      {result?.reasoning_text && (
        <details className="px-4 py-2 border-t border-border text-xs text-muted-foreground">
          <summary className="cursor-pointer">model reasoning</summary>
          <p className="mt-1 whitespace-pre-wrap">{result.reasoning_text}</p>
        </details>
      )}
    </Card>
  );
}

function StatusStrip({
  runtime,
  runtimeError,
  cam,
  result,
}: {
  runtime: RuntimeStatus | null;
  runtimeError: string | null;
  cam: RuntimeStatus["cameras"][number] | null;
  result: InferenceResult | null;
}) {
  const model = runtime?.model;
  const guard = result?.guard ?? model?.guard ?? null;
  const modelError = result?.model_error ?? cam?.worker?.last_error ?? null;

  let modelTone: "ok" | "warn" | "danger" | "neutral" = "neutral";
  let modelText = model?.label || model?.model || model?.backend || "—";
  let modelSub: string | null = null;
  if (result?.status === "blocked_constrained_mode") {
    modelTone = "danger";
    modelText = "blocked: constrained mode";
    modelSub = guard?.message ?? "json_schema is on but the server does not enforce it (reasoning parser). Disable json_schema or start the no-reasoning entry.";
  } else if (result?.status === "inference_unavailable") {
    modelTone = "danger";
    modelText = "inference unavailable";
    modelSub = modelError ?? guard?.message ?? null;
  } else if (model?.backend === "mock") {
    modelTone = "ok";
    modelText = "mock adapter";
    modelSub = "synthetic detections";
  } else if (guard) {
    modelTone = guard.ok ? "ok" : "danger";
    modelSub = guard.ok ? `guard ok · ${model?.model ?? ""}` : guard.message;
  } else if (model) {
    modelSub = `${model.backend} · guard not run`;
  }

  return (
    <div className="card px-4 py-3 grid gap-4 grid-cols-2 md:grid-cols-4 xl:grid-cols-6">
      <Stat
        label="Camera"
        value={<CameraStateChip state={cam?.state} />}
        sub={cam ? `${fmtNum(cam.fps)} fps · ${cam.codec ?? "—"}${cam.source_width ? ` · ${cam.source_width}×${cam.source_height}` : ""}` : runtimeError ?? "not running"}
      />
      <Stat
        label="Frames"
        value={cam?.frames_published ?? "—"}
        sub={cam ? `${cam.frames_dropped} dropped · ${cam.kind === "file" ? `${cam.loops} loops` : `${cam.reconnects} reconnects`}` : undefined}
        tone={cam && cam.frames_dropped > 0 ? "warn" : undefined}
      />
      <Stat label="Model" value={modelText} sub={modelSub ?? undefined} tone={modelTone} className="col-span-2" />
      <Stat
        label="Transport"
        value={runtime ? `q ${runtime.transport.queue_depth}` : "—"}
        sub={
          runtime
            ? `p2e p50 ${fmtMs(runtime.transport.packet_to_event_ms.p50)} · ${runtime.transport.posted} posted${runtime.transport.failed ? ` · ${runtime.transport.failed} failed` : ""}`
            : undefined
        }
        tone={runtime && (runtime.transport.failed > 0 || runtime.transport.queue_depth > 10) ? "warn" : undefined}
      />
      <Stat
        label="Last result"
        value={result?.status === "ok" ? fmtMs(result.inference_ms) : result?.status ?? "—"}
        sub={result?.status === "ok" ? `capture→result ${fmtMs(result.capture_to_result_ms)} · rules ${fmtNum(result.rule_ms, 2)} ms` : cam?.worker ? `${cam.worker.frames_sampled} sampled · ${cam.worker.inference_failures} failures` : undefined}
      />
      {cam?.last_error && (
        <p className="col-span-full text-xs text-destructive break-all">camera: {cam.last_error}</p>
      )}
      {modelError && result?.status !== "ok" && modelTone !== "danger" && (
        <p className="col-span-full text-xs text-warn break-all">model: {modelError}</p>
      )}
    </div>
  );
}

function EventRow({ e }: { e: SafetyEvent }) {
  return (
    <li className="px-3 py-2 text-sm space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <SeverityChip severity={e.severity} />
        <span className="font-medium">{ruleLabel(e.rule_id)}</span>
        <span className="ml-auto mono text-muted-foreground">{fmtClock(e.timestamp)}</span>
      </div>
      <p className="text-muted-foreground line-clamp-2">{e.summary}</p>
      <div className="flex gap-2 text-xs text-muted-foreground items-center flex-wrap">
        <span>conf {fmtPct(e.confidence)}</span>
        {e.human_review_required && <span className="text-warn">review required</span>}
        <SourceKindBadge kind={e.source_kind} />
      </div>
    </li>
  );
}
