import { useEffect, useMemo, useRef, useState } from "react";
import { Eye, EyeOff, PlugZap, RefreshCw, Upload } from "lucide-react";
import {
  api,
  apiErrorMessage,
  RULE_IDS,
  type Camera,
  type CameraIn,
  type CameraProfile,
  type CameraTestResult,
  type Playback,
  type UploadRecord,
  type UploadSourceKind,
  type UsbDevice,
} from "@/lib/api";
import { fmtNum, ruleLabel } from "@/lib/utils";
import { Button, Field, Input, Notice, Select, Toggle } from "./ui";
import { ZoneCanvas } from "./zone-canvas";
import { TestResultView } from "./test-result";
import { SourceKindBadge } from "./source-kind-badge";

export function fmtBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function describeUpload(u: UploadRecord): string {
  return [
    u.width && u.height ? `${u.width}×${u.height}` : null,
    u.fps ? `${fmtNum(u.fps, u.fps % 1 ? 2 : 0)} fps` : null,
    u.duration_s ? `${u.duration_s.toFixed(1)} s` : null,
    u.codec,
    fmtBytes(u.size_bytes),
  ].filter(Boolean).join(" · ");
}

export interface CameraFormValues extends CameraIn {
  port: number | null;
}

const EMPTY: CameraFormValues = {
  name: "",
  profile: "generic_rtsp",
  host: "",
  port: null,
  username: "",
  password: "",
  stream_path: "",
  stream_quality: "main",
  channel: 1,
  rtsp_transport: "tcp",
  enabled: true,
  location: "",
  zones: [],
  rules: [],
  source_url: "",
  device: "",
  capture_width: null,
  capture_height: null,
  capture_fps: null,
  capture_format: "",
  upload_id: "",
  playback: "loop",
};

function fromCamera(c: Camera): CameraFormValues {
  return {
    name: c.name,
    profile: c.profile,
    host: c.host,
    port: c.port,
    username: c.username,
    password: "",
    stream_path: c.stream_path,
    stream_quality: c.stream_quality,
    channel: c.channel,
    rtsp_transport: c.rtsp_transport,
    enabled: c.enabled,
    location: c.location ?? "",
    zones: c.zones.map((z) => ({ ...z, polygon: z.polygon.map((p) => [...p]) })),
    rules: [...c.rules],
    source_url: c.source_url,
    device: c.device,
    capture_width: c.capture_width,
    capture_height: c.capture_height,
    capture_fps: c.capture_fps,
    capture_format: c.capture_format,
    upload_id: c.upload_id,
    playback: c.playback,
  };
}

type Setter = <K extends keyof CameraFormValues>(k: K, v: CameraFormValues[K]) => void;

/** USB camera: device list from the API, then resolution/format and frame rate from its modes. */
function UsbSection({ values, set }: { values: CameraFormValues; set: Setter }) {
  const [devices, setDevices] = useState<UsbDevice[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api.cameras.usbDevices();
      setDevices(res.devices);
      setNote(res.note);
      if (!values.device && res.devices.length > 0) set("device", res.devices[0].path);
    } catch (e) {
      setErr(apiErrorMessage(e, "Could not list USB devices"));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const device = devices?.find((d) => d.path === values.device);
  const modes = useMemo(() => (device?.modes ?? []).map((m) => ({ ...m, key: `${m.pixel_format}:${m.width}x${m.height}` })), [device]);
  const modeKey = values.capture_width && values.capture_height ? `${values.capture_format || ""}:${values.capture_width}x${values.capture_height}` : "";
  const mode = modes.find((m) => m.key === modeKey) ?? modes.find((m) => m.key.endsWith(`:${values.capture_width}x${values.capture_height}`));
  const fpsChoices = mode?.fps ?? Array.from(new Set(modes.flatMap((m) => m.fps))).sort((a, b) => b - a);

  return (
    <div className="space-y-3">
      <div className="grid gap-4 sm:grid-cols-[1fr_auto] items-end">
        <Field label="USB device" hint={device?.error ?? note ?? "Capture devices under /dev/video*. Metadata nodes are hidden."}>
          <Select value={values.device ?? ""} onChange={(e) => { set("device", e.target.value); set("capture_width", null); set("capture_height", null); set("capture_fps", null); set("capture_format", ""); }} disabled={loading}>
            {(devices ?? []).length === 0 && <option value="">{loading ? "Scanning…" : "No USB camera found"}</option>}
            {(devices ?? []).map((d) => (
              <option key={d.path} value={d.path}>{d.name} — {d.path}{d.error ? " (unavailable)" : ""}</option>
            ))}
          </Select>
        </Field>
        <Button onClick={() => void load()} busy={loading} title="Rescan devices"><RefreshCw className="h-3.5 w-3.5" /> Rescan</Button>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Resolution and format" hint="Driver default when blank. MJPG usually offers the higher frame rates.">
          <Select value={mode?.key ?? ""} disabled={!device} onChange={(e) => { const m = modes.find((x) => x.key === e.target.value); set("capture_width", m?.width ?? null); set("capture_height", m?.height ?? null); set("capture_format", m?.pixel_format ?? ""); if (m && values.capture_fps && !m.fps.includes(values.capture_fps)) set("capture_fps", m.fps[0] ?? null); }}>
            <option value="">Driver default</option>
            {modes.map((m) => <option key={m.key} value={m.key}>{m.width}×{m.height} · {m.pixel_format}{m.fps.length ? ` · up to ${m.fps[0]} fps` : ""}</option>)}
          </Select>
        </Field>
        <Field label="Frame rate" hint="Rates the device offers for the chosen mode">
          <Select value={values.capture_fps ?? ""} disabled={!device} onChange={(e) => set("capture_fps", e.target.value ? parseFloat(e.target.value) : null)}>
            <option value="">Driver default</option>
            {fpsChoices.map((f) => <option key={f} value={f}>{f} fps</option>)}
          </Select>
        </Field>
      </div>
      {err && <Notice kind="error">{err}</Notice>}
      {devices && devices.length === 0 && <Notice kind="warn">{note ?? "No USB camera found."}</Notice>}
    </div>
  );
}

/** Uploaded video: pick an existing upload or upload a new one, then loop or play once. */
function UploadSection({ values, set, onUploaded }: { values: CameraFormValues; set: Setter; onUploaded?: () => void }) {
  const [uploads, setUploads] = useState<UploadRecord[]>([]);
  const [kind, setKind] = useState<UploadSourceKind>("recorded");
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const load = async () => {
    try { setUploads(await api.cameras.uploads.list()); }
    catch (e) { setErr(apiErrorMessage(e, "Could not list uploads")); }
  };
  useEffect(() => { void load(); }, []);

  const upload = async () => {
    if (!file) return;
    setErr(null);
    setProgress(0);
    try {
      const rec = await api.cameras.uploads.upload(file, kind, setProgress);
      await load();
      set("upload_id", rec.id);
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      onUploaded?.();
    } catch (e) {
      setErr(apiErrorMessage(e, "Upload failed"));
    } finally {
      setProgress(null);
    }
  };

  const selected = uploads.find((u) => u.id === values.upload_id);
  const uploading = progress !== null;
  return (
    <div className="space-y-3">
      <div className="grid gap-4 sm:grid-cols-[1fr_12rem]">
        <Field label="Video to play" hint={selected ? <span className="flex items-center gap-2 flex-wrap"><SourceKindBadge kind={selected.source_kind === "generated" ? "uploaded_generated" : "uploaded_recorded"} />{describeUpload(selected)}</span> : "Pick an uploaded file, or upload a new one below. Uploads always play at their own frame rate."}>
          <Select value={values.upload_id ?? ""} onChange={(e) => set("upload_id", e.target.value)} disabled={uploading}>
            <option value="">{uploads.length ? "Choose an uploaded video…" : "No uploads yet"}</option>
            {uploads.map((u) => <option key={u.id} value={u.id}>{u.filename} · {u.source_kind} · {fmtBytes(u.size_bytes)}</option>)}
          </Select>
        </Field>
        <Field label="Playback">
          <Select value={values.playback ?? "loop"} onChange={(e) => set("playback", e.target.value as Playback)}>
            <option value="loop">Loop</option>
            <option value="once">Play once, then stop</option>
          </Select>
        </Field>
      </div>
      <div className="card p-3 space-y-3">
        <p className="text-sm font-medium flex items-center gap-2"><Upload className="h-4 w-4" /> Upload a new file</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="File" hint="MP4, MOV or MKV. The size limit is set on the server (default 2 GB).">
            <input ref={fileRef} type="file" accept=".mp4,.mov,.mkv,video/mp4,video/quicktime,video/x-matroska" disabled={uploading} onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm text-muted-foreground" />
          </Field>
          <Field label="What is this footage?" hint="Shown as a badge on Live, every event and every run report made from it.">
            <div className="flex items-center gap-4 pt-1.5 text-sm">
              <label className="inline-flex items-center gap-1.5"><input type="radio" name="upload-kind" checked={kind === "recorded"} onChange={() => setKind("recorded")} disabled={uploading} /> Recorded (real camera)</label>
              <label className="inline-flex items-center gap-1.5"><input type="radio" name="upload-kind" checked={kind === "generated"} onChange={() => setKind("generated")} disabled={uploading} /> Generated (simulation, AI)</label>
            </div>
          </Field>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="primary" onClick={() => void upload()} busy={uploading} disabled={!file}>
            <Upload className="h-3.5 w-3.5" /> {uploading ? `Uploading ${Math.round((progress ?? 0) * 100)}%` : "Upload"}
          </Button>
          {file && !uploading && <span className="text-xs text-muted-foreground">{file.name} · {fmtBytes(file.size)}</span>}
          {uploading && <div className="flex-1 h-1.5 rounded bg-secondary overflow-hidden"><div className="h-full bg-primary transition-all" style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} /></div>}
        </div>
      </div>
      {err && <Notice kind="error">{err}</Notice>}
    </div>
  );
}

/** Fill the path template the way the backend does (CameraProfile.stream_path). */
export function templatePath(profile: CameraProfile, quality: "main" | "sub", channel: number): string {
  const tpl = quality === "sub" ? profile.sub_path : profile.main_path;
  return tpl
    .split("{channel2}")
    .join(String(channel).padStart(2, "0"))
    .split("{channel}")
    .join(String(channel));
}

export function CameraForm({
  profiles,
  initial,
  onSaved,
  onCancel,
  onUploaded,
}: {
  profiles: CameraProfile[];
  initial: Camera | null;
  onSaved: (cam: Camera) => void;
  onCancel: () => void;
  /** called after a successful upload so the parent can refresh its uploads list */
  onUploaded?: () => void;
}) {
  const [values, setValues] = useState<CameraFormValues>(initial ? fromCamera(initial) : EMPTY);
  const [showPassword, setShowPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<CameraTestResult | null>(null);

  useEffect(() => {
    setValues(initial ? fromCamera(initial) : EMPTY);
    setTest(null);
    setError(null);
  }, [initial]);

  const profile = useMemo(
    () => profiles.find((p) => p.model_type === values.profile) ?? null,
    [profiles, values.profile]
  );
  const connector = profile?.connector ?? "network";
  const needsHost = connector === "network" && (profile?.requires_host ?? true);
  const canTest = connector === "network" || connector === "rtsp_url" || connector === "usb" || connector === "upload";
  const linkHasCreds = /^rtsps?:\/\/[^/@\s]+@/i.test((values.source_url ?? "").trim());
  const autoPath = profile ? templatePath(profile, values.stream_quality, values.channel) : "";
  const pathIsAuto = values.stream_path.trim() === "" || values.stream_path === autoPath;

  const set = <K extends keyof CameraFormValues>(k: K, v: CameraFormValues[K]) =>
    setValues((s) => ({ ...s, [k]: v }));

  const onProfileChange = (next: string) => {
    const p = profiles.find((x) => x.model_type === next);
    setValues((s) => {
      const prev = profiles.find((x) => x.model_type === s.profile);
      const prevAuto = prev ? templatePath(prev, s.stream_quality, s.channel) : "";
      const keepPath = s.stream_path !== "" && s.stream_path !== prevAuto;
      return {
        ...s,
        profile: next,
        port: p && p.requires_host ? p.default_port : null,
        stream_path: keepPath ? s.stream_path : p ? templatePath(p, s.stream_quality, s.channel) : "",
      };
    });
  };

  const onQualityOrChannel = (patch: Partial<Pick<CameraFormValues, "stream_quality" | "channel">>) => {
    setValues((s) => {
      const p = profiles.find((x) => x.model_type === s.profile);
      const wasAuto = !p || s.stream_path === "" || s.stream_path === templatePath(p, s.stream_quality, s.channel);
      const next = { ...s, ...patch };
      if (p && wasAuto) next.stream_path = templatePath(p, next.stream_quality, next.channel);
      return next;
    });
  };

  const payload = (): CameraIn => ({
    ...values,
    host: needsHost ? values.host.trim() : "",
    port: needsHost ? values.port : null,
    username: needsHost || connector === "rtsp_url" ? values.username : "",
    password: needsHost || connector === "rtsp_url" ? values.password : "",
    stream_path: needsHost ? values.stream_path.trim() : "",
    source_url: (values.source_url ?? "").trim(),
    location: values.location?.trim() ? values.location.trim() : null,
    zones: values.zones.map((z) => ({ ...z, zone_id: z.zone_id.trim() || "zone" })),
  });

  const validate = (): string | null => {
    if (!values.name.trim()) return "Name is required.";
    if (needsHost && !values.host.trim()) return `Host is required for ${profile?.label ?? "this profile"}.`;
    if (connector === "rtsp_url" && !/^rtsps?:\/\//i.test((values.source_url ?? "").trim())) return "Paste a link that starts with rtsp:// or rtsps://.";
    if (connector === "usb" && !values.device) return "Choose a USB camera device.";
    if (connector === "upload" && !values.upload_id) return "Choose or upload a video to play.";
    const short = values.zones.filter((z) => z.polygon.length < 3);
    if (short.length) return `Zone${short.length > 1 ? "s" : ""} ${short.map((z) => z.zone_id).join(", ")} need at least 3 vertices.`;
    const ids = values.zones.map((z) => z.zone_id.trim());
    if (new Set(ids).size !== ids.length) return "Zone ids must be unique.";
    return null;
  };

  const save = async () => {
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = payload();
      const saved = initial
        ? await api.cameras.update(initial.camera_id, body)
        : await api.cameras.create(body);
      onSaved(saved);
    } catch (err) {
      setError(apiErrorMessage(err, "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    setError(null);
    try {
      // Unsaved form values are probed as-is. With the password left blank on an
      // existing camera the server uses the stored (encrypted) one for this
      // camera_id, so edited host/path values are still what gets probed.
      const res = await api.cameras.testUnsaved({ ...payload(), camera_id: initial?.camera_id });
      setTest(res);
    } catch (err) {
      setError(apiErrorMessage(err, "Test failed"));
    } finally {
      setTesting(false);
    }
  };

  const toggleRule = (rule: string) =>
    set("rules", values.rules.includes(rule) ? values.rules.filter((r) => r !== rule) : [...values.rules, rule]);

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name">
          <Input value={values.name} onChange={(e) => set("name", e.target.value)} placeholder="Line 3 east bay" required maxLength={80} />
        </Field>
        <Field label="Profile" hint={profile?.notes || undefined}>
          <Select value={values.profile} onChange={(e) => onProfileChange(e.target.value)}>
            <optgroup label="Network cameras (host + path)">
              {profiles.filter((p) => p.connector === "network").map((p) => (
                <option key={p.model_type} value={p.model_type}>{p.label}</option>
              ))}
            </optgroup>
            <optgroup label="Other video feeds">
              {profiles.filter((p) => p.connector !== "network").map((p) => (
                <option key={p.model_type} value={p.model_type}>{p.label}</option>
              ))}
            </optgroup>
          </Select>
        </Field>
      </div>

      {connector === "rtsp_url" && (
        <div className="space-y-4">
          <Field
            label="Stream link"
            hint={linkHasCreds
              ? "This link contains a username and password. They will be taken out of the link, stored encrypted like any camera password, and never shown or logged."
              : "Full rtsp:// or rtsps:// address, for example rtsp://192.0.2.50:554/stream1. Credentials can stay in the link or go in the fields below."}
          >
            <Input value={values.source_url ?? ""} onChange={(e) => set("source_url", e.target.value)} placeholder="rtsp://192.0.2.50:554/stream1" autoComplete="off" spellCheck={false} className="mono" />
          </Field>
          <div className="grid gap-4 sm:grid-cols-[1fr_1fr_6rem]">
            <Field label="Username" hint="Optional. Overrides a username inside the link.">
              <Input value={values.username} onChange={(e) => set("username", e.target.value)} autoComplete="off" />
            </Field>
            <Field label="Password" hint={initial?.has_password ? "A password is stored. Leave blank to keep it." : "Optional. Overrides a password inside the link."}>
              <Input type={showPassword ? "text" : "password"} value={values.password} onChange={(e) => set("password", e.target.value)} placeholder={initial?.has_password ? "(unchanged)" : ""} autoComplete="new-password" />
            </Field>
            <Field label="Transport">
              <Select value={values.rtsp_transport} onChange={(e) => set("rtsp_transport", e.target.value as "tcp" | "udp")}>
                <option value="tcp">tcp</option>
                <option value="udp">udp</option>
              </Select>
            </Field>
          </div>
        </div>
      )}

      {connector === "usb" && <UsbSection values={values} set={set} />}
      {connector === "upload" && <UploadSection values={values} set={set} onUploaded={onUploaded} />}
      {connector === "browser" && (
        <Notice kind="info" className="text-sm space-y-1">
          <p>Open the Live page in the browser whose camera you want to share and press <b>Share camera</b>. On a laptop you pick the camera from a list; on a phone you choose front or back.</p>
          <p>Browsers only allow camera access on <span className="mono">localhost</span> or over HTTPS. For a phone or another computer on the LAN, enable the optional HTTPS front door (README: <i>Browser camera from another device</i>).</p>
        </Notice>
      )}

      {needsHost && (
        <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
          <Field label="Host">
            <Input value={values.host} onChange={(e) => set("host", e.target.value)} placeholder="192.0.2.20" />
          </Field>
          <Field label="Port">
            <Input
              type="number"
              min={1}
              max={65535}
              value={values.port ?? ""}
              onChange={(e) => set("port", e.target.value === "" ? null : Number(e.target.value))}
              placeholder={String(profile?.default_port ?? "")}
            />
          </Field>
        </div>
      )}

      {needsHost && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Username">
            <Input value={values.username} onChange={(e) => set("username", e.target.value)} autoComplete="off" />
          </Field>
          <Field
            label="Password"
            hint={initial?.has_password ? "A password is stored. Leave blank to keep it." : profile?.requires_auth ? "Required by this profile." : undefined}
          >
            <div className="relative">
              <Input
                type={showPassword ? "text" : "password"}
                value={values.password}
                onChange={(e) => set("password", e.target.value)}
                placeholder={initial?.has_password ? "(unchanged)" : ""}
                autoComplete="new-password"
                className="pr-9"
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setShowPassword((s) => !s)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </Field>
        </div>
      )}

      {needsHost && (
        <div className="grid gap-4 sm:grid-cols-[8rem_1fr_6rem_6rem]">
          <Field label="Quality">
            <Select value={values.stream_quality} onChange={(e) => onQualityOrChannel({ stream_quality: e.target.value as "main" | "sub" })}>
              <option value="main">main</option>
              <option value="sub">sub</option>
            </Select>
          </Field>
          <Field
            label={
              <span className="flex items-center gap-2">
                Stream path
                {!pathIsAuto && profile && (
                  <button type="button" className="text-primary normal-case tracking-normal hover:underline" onClick={() => set("stream_path", autoPath)}>
                    reset to {autoPath || "default"}
                  </button>
                )}
              </span>
            }
            hint={profile ? `Example: main ${profile.example_main_path || "—"} · sub ${profile.example_sub_path || "—"}` : undefined}
          >
            <Input value={values.stream_path} onChange={(e) => set("stream_path", e.target.value)} placeholder={autoPath} className="mono" />
          </Field>
          <Field label="Channel">
            <Input type="number" min={1} max={64} value={values.channel} onChange={(e) => onQualityOrChannel({ channel: Math.max(1, Number(e.target.value) || 1) })} />
          </Field>
          <Field label="Transport">
            <Select value={values.rtsp_transport} onChange={(e) => set("rtsp_transport", e.target.value as "tcp" | "udp")}>
              <option value="tcp">tcp</option>
              <option value="udp">udp</option>
            </Select>
          </Field>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-[1fr_auto] items-end">
        <Field label="Location" hint="Free text shown with events.">
          <Input value={values.location ?? ""} onChange={(e) => set("location", e.target.value)} placeholder="Assembly hall, bay 3" />
        </Field>
        <Toggle checked={values.enabled} onChange={(v) => set("enabled", v)} label="Enabled" />
      </div>

      <div>
        <span className="label">Rules</span>
        <p className="text-xs text-muted-foreground mb-2">None selected = all rules run.</p>
        <div className="flex flex-wrap gap-2">
          {RULE_IDS.map((r) => (
            <label key={r} className="inline-flex items-center gap-2 card px-2.5 py-1.5 cursor-pointer hover:bg-secondary/50">
              <input type="checkbox" checked={values.rules.includes(r)} onChange={() => toggleRule(r)} />
              <span className="text-sm">{ruleLabel(r)}</span>
              <span className="mono text-muted-foreground hidden md:inline">{r}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <span className="label">Zones</span>
        <ZoneCanvas
          zones={values.zones}
          onChange={(z) => set("zones", z)}
          cameraId={initial?.camera_id ?? null}
          snapshotAvailable={!!initial?.runtime}
        />
      </div>

      {error && <Notice kind="error">{error}</Notice>}
      {test && <TestResultView result={test} />}

      <div className="flex items-center gap-2 flex-wrap pt-2 border-t border-border">
        <Button type="submit" variant="primary" busy={saving}>
          {initial ? "Save changes" : "Add camera"}
        </Button>
        {canTest && (
          <Button onClick={() => void runTest()} busy={testing} title="Probe the stream, device or file with the current form values">
            <PlugZap className="h-3.5 w-3.5" /> {connector === "upload" ? "Check file" : "Test connection"}
          </Button>
        )}
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        {initial && <span className="ml-auto mono text-muted-foreground">{initial.camera_id}</span>}
      </div>
    </form>
  );
}
