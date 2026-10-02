import { useState } from "react";
import { Pencil, PlugZap, Plus, Trash2 } from "lucide-react";
import { api, apiErrorMessage, type Camera, type CameraTestResult } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { fmtNum } from "@/lib/utils";
import { Button, Card, Chip, Empty, Notice, Toggle } from "@/components/ui";
import { CameraStateChip } from "@/components/status-chip";
import { CameraForm } from "@/components/camera-form";
import { TestResultView } from "@/components/test-result";

type Mode = { kind: "list" } | { kind: "new" } | { kind: "edit"; camera: Camera };

export function CamerasPage() {
  const cameras = usePoll(() => api.cameras.list(), 4000);
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
              }}
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
        <Empty>No cameras configured. Add a synthetic feed to see the pipeline run without hardware.</Empty>
      )}
      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {list.map((c) => (
          <CameraCard
            key={c.camera_id}
            camera={c}
            onEdit={() => setMode({ kind: "edit", camera: c })}
            onChanged={() => void cameras.refresh()}
          />
        ))}
      </div>
    </div>
  );
}

function CameraCard({ camera, onEdit, onChanged }: { camera: Camera; onEdit: () => void; onChanged: () => void }) {
  const [busy, setBusy] = useState<"toggle" | "test" | "delete" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<CameraTestResult | null>(null);
  const rt = camera.runtime;
  const requiresHost = !["synthetic", "browser_webrtc"].includes(camera.profile);

  const run = async (kind: "toggle" | "test" | "delete", fn: () => Promise<void>) => {
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
