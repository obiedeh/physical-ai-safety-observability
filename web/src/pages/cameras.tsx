import { useState } from "react";
import { Film, Pencil, PlugZap, Plus, RotateCcw, Trash2 } from "lucide-react";
import { api, apiErrorMessage, type Camera, type CameraTestResult, type UploadRecord } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { fmtNum } from "@/lib/utils";
import { Button, Card, Chip, Empty, Notice, Toggle } from "@/components/ui";
import { CameraStateChip } from "@/components/status-chip";
import { SourceKindBadge } from "@/components/source-kind-badge";
import { CameraForm, describeUpload } from "@/components/camera-form";
import { TestResultView } from "@/components/test-result";

type Mode = { kind: "list" } | { kind: "new" } | { kind: "edit"; camera: Camera };

export function CamerasPage() {
  const cameras = usePoll(() => api.cameras.list(), 4000);
  const uploads = usePoll(() => api.cameras.uploads.list(), 10000);
  const profiles = usePoll(() => api.cameras.profiles(), 0);
  const [mode, setMode] = useState<Mode>({ kind: "list" });
  const [notice, setNotice] = useState<string | null>(null);

  const list = cameras.data ?? [];

  if (mode.kind !== "list") {
    const editing = mode.kind === "edit" ? mode.camera : null;
    return (
      <div className="space-y-4 max-w-4xl">
        <div className="flex items-center justify-between">
          <h1 className="text-base font-semibold">{editing ? `Edit ${editing.name}` : "Add camera"}</h1>
          <Button variant="ghost" onClick={() => setMode({ kind: "list" })}>
            Back to list
          </Button>
        </div>
        <Card>
          {profiles.data ? (
            <CameraForm
              profiles={profiles.data}
              initial={editing}
              onCancel={() => setMode({ kind: "list" })}
              onSaved={(cam) => {
                setNotice(`${editing ? "Updated" : "Added"} ${cam.name}.`);
                setMode({ kind: "list" });
                void cameras.refresh();
                void uploads.refresh();
              }}
              onUploaded={() => void uploads.refresh()}
            />
          ) : (
            <p className="text-sm text-muted-foreground">{profiles.error ?? "Loading profiles…"}</p>
          )}
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h1 className="text-base font-semibold">
          Cameras <span className="text-muted-foreground font-normal">({list.length})</span>
        </h1>
        <Button variant="primary" onClick={() => setMode({ kind: "new" })}>
          <Plus className="h-4 w-4" /> Add camera
        </Button>
      </div>
      {notice && (
        <Notice kind="ok" className="flex justify-between">
          <span>{notice}</span>
          <button type="button" className="underline" onClick={() => setNotice(null)}>
            dismiss
          </button>
        </Notice>
      )}
      {cameras.error && <Notice kind="error">{cameras.error}</Notice>}
      {!cameras.loading && list.length === 0 && (
        <Empty>No cameras configured. Add a network camera, paste an RTSP link, pick a USB camera, upload a video, share a browser camera, or add a synthetic feed to see the pipeline run without hardware.</Empty>
      )}
      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {list.map((c) => (
          <CameraCard
            key={c.camera_id}
            camera={c}
            onEdit={() => setMode({ kind: "edit", camera: c })}
            onChanged={() => { void cameras.refresh(); void uploads.refresh(); }}
          />
        ))}
      </div>
      {((uploads.data?.length ?? 0) > 0 || list.some((c) => c.connector === "upload")) && (
        <UploadsCard uploads={uploads.data ?? []} cameras={list} onChanged={() => { void uploads.refresh(); void cameras.refresh(); }} />
      )}
    </div>
  );
}

function UploadsCard({ uploads, cameras, onChanged }: { uploads: UploadRecord[]; cameras: Camera[]; onChanged: () => void }) {
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const names = new Map(cameras.map((c) => [c.camera_id, c.name]));
  const remove = async (u: UploadRecord) => {
    setBusy(u.id);
    setError(null);
    try { await api.cameras.uploads.remove(u.id); onChanged(); }
    catch (e) { setError(apiErrorMessage(e, "Delete failed")); }
    finally { setBusy(""); }
  };
  return (
    <Card
      title={<span className="flex items-center gap-2"><Film className="h-4 w-4" /> Uploaded videos <span className="text-muted-foreground font-normal">({uploads.length})</span></span>}
      actions={<span className="text-xs text-muted-foreground">stored next to the database, outside the repository · delete removes the file</span>}
      bodyClassName="p-0"
    >
      {uploads.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">No uploads yet. Add a camera with the <b>Uploaded video</b> profile to upload an MP4, MOV or MKV.</p>
      ) : (
        <ul className="divide-y divide-border">
          {uploads.map((u) => (
            <li key={u.id} className="flex items-center gap-3 px-4 py-2 text-sm flex-wrap">
              <SourceKindBadge kind={u.source_kind === "generated" ? "uploaded_generated" : "uploaded_recorded"} />
              <span className="font-medium">{u.filename}</span>
              <span className="text-muted-foreground text-xs tabular-nums">{describeUpload(u)}</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {u.camera_ids.length ? `used by ${u.camera_ids.map((id) => names.get(id) ?? id).join(", ")}` : "not used"}
              </span>
              <Button size="sm" variant="ghost" className="text-destructive" busy={busy === u.id} disabled={u.camera_ids.length > 0} title={u.camera_ids.length ? "Delete or re-point the cameras using this file first" : "Delete the file"} onClick={() => void remove(u)}>
                <Trash2 className="h-3.5 w-3.5" /> Delete
              </Button>
            </li>
          ))}
        </ul>
      )}
      {error && <Notice kind="error" className="m-3">{error}</Notice>}
    </Card>
  );
}

function CameraCard({ camera, onEdit, onChanged }: { camera: Camera; onEdit: () => void; onChanged: () => void }) {
  const [busy, setBusy] = useState<"toggle" | "test" | "delete" | "restart" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<CameraTestResult | null>(null);
  const rt = camera.runtime;
  const requiresHost = camera.connector === "network" || camera.connector === "rtsp_url";
  const canTest = camera.connector !== "browser" && camera.connector !== "synthetic";
  const canRestart = camera.enabled && (camera.connector === "upload" || rt?.state === "error" || rt?.state === "ended");

  const run = async (kind: "toggle" | "test" | "delete" | "restart", fn: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      title={
        <span className="flex items-center gap-2 min-w-0">
          <span className="truncate">{camera.name}</span>
          <Chip tone="neutral">{camera.profile}</Chip>
          <SourceKindBadge kind={camera.source_kind} />
          {!camera.enabled && <Chip tone="neutral">disabled</Chip>}
        </span>
      }
      actions={
        <Toggle
          checked={camera.enabled}
          disabled={busy !== null}
          title={camera.enabled ? "Disable camera" : "Enable camera"}
          onChange={(v) =>
            void run("toggle", async () => {
              await api.cameras.setEnabled(camera.camera_id, v);
              onChanged();
            })
          }
        />
      }
      bodyClassName="p-3 space-y-3"
    >
      <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
        <CameraStateChip state={rt?.state} />
        {rt && (
          <>
            <span>{fmtNum(rt.fps)} fps</span>
            {rt.codec && <span>{rt.codec}</span>}
            {rt.source_width && <span>{rt.source_width}×{rt.source_height}</span>}
            {rt.frames_dropped > 0 && <span className="text-warn">{rt.frames_dropped} dropped</span>}
            {rt.reconnects > 0 && <span className="text-warn">{rt.reconnects} reconnects</span>}
            {camera.connector === "upload" && <span>{rt.loops} loops</span>}
            {rt.worker && <span>{rt.worker.events_emitted} events</span>}
          </>
        )}
      </div>
      {rt?.last_error && <p className="text-xs text-destructive break-all">{rt.last_error}</p>}
      {rt?.worker?.last_error && <p className="text-xs text-warn break-all">worker: {rt.worker.last_error}</p>}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        {requiresHost && (
          <>
            <dt className="text-muted-foreground">url</dt>
            <dd className="mono break-all">{camera.masked_url || `${camera.host}:${camera.port ?? ""}${camera.effective_stream_path}`}</dd>
            <dt className="text-muted-foreground">auth</dt>
            <dd>{camera.username || "—"}{camera.has_password ? " · password stored" : ""} · {camera.rtsp_transport}</dd>
          </>
        )}
        {camera.connector === "usb" && (
          <>
            <dt className="text-muted-foreground">device</dt>
            <dd className="mono">{camera.device}{camera.capture_width ? ` · ${camera.capture_width}×${camera.capture_height}` : ""}{camera.capture_format ? ` ${camera.capture_format}` : ""}{camera.capture_fps ? ` @ ${camera.capture_fps} fps` : ""}</dd>
          </>
        )}
        {camera.connector === "upload" && (
          <>
            <dt className="text-muted-foreground">video</dt>
            <dd>{camera.upload ? `${camera.upload.filename} · ${describeUpload(camera.upload)}` : "upload missing"} · {camera.playback === "once" ? "play once" : "loop"}</dd>
          </>
        )}
        <dt className="text-muted-foreground">location</dt>
        <dd>{camera.location || "—"}</dd>
        <dt className="text-muted-foreground">rules</dt>
        <dd>{camera.rules.length ? camera.rules.join(", ") : "all"}</dd>
        <dt className="text-muted-foreground">zones</dt>
        <dd>{camera.zones.length ? camera.zones.map((z) => `${z.zone_id} (${z.type})`).join(", ") : "none"}</dd>
        <dt className="text-muted-foreground">id</dt>
        <dd className="mono">{camera.camera_id}</dd>
      </dl>

      {error && <Notice kind="error">{error}</Notice>}
      {test && <TestResultView result={test} />}

      <div className="flex items-center gap-2 flex-wrap pt-1">
        {canTest && (
          <Button
            size="sm"
            busy={busy === "test"}
            onClick={() =>
              void run("test", async () => {
                setTest(null);
                setTest(await api.cameras.testSaved(camera.camera_id));
              })
            }
          >
            <PlugZap className="h-3.5 w-3.5" /> Test
          </Button>
        )}
        {canRestart && (
          <Button size="sm" busy={busy === "restart"} title={camera.connector === "upload" ? "Play the video again from the start" : "Reconnect now"} onClick={() => void run("restart", async () => { await api.cameras.restart(camera.camera_id); onChanged(); })}>
            <RotateCcw className="h-3.5 w-3.5" /> {camera.connector === "upload" ? "Replay" : "Reconnect"}
          </Button>
        )}
        <Button size="sm" onClick={onEdit}>
          <Pencil className="h-3.5 w-3.5" /> Edit
        </Button>
        {confirmDelete ? (
          <span className="ml-auto flex items-center gap-1 text-xs">
            <span className="text-destructive">Delete {camera.name}?</span>
            <Button
              size="sm"
              variant="danger"
              busy={busy === "delete"}
              onClick={() =>
                void run("delete", async () => {
                  await api.cameras.remove(camera.camera_id);
                  onChanged();
                })
              }
            >
              Confirm
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
          </span>
        ) : (
          <Button size="sm" variant="ghost" className="ml-auto text-destructive" onClick={() => setConfirmDelete(true)}>
            <Trash2 className="h-3.5 w-3.5" /> Delete
          </Button>
        )}
      </div>
    </Card>
  );
}
