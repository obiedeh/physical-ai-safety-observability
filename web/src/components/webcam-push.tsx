import { useCallback, useEffect, useRef, useState } from "react";
import { Lock, SwitchCamera, Video, VideoOff } from "lucide-react";
import { api } from "@/lib/api";
import { Button, Notice, Select } from "./ui";

const PUSH_FPS = 5;
const MAX_WIDTH = 960;
const HTTPS_PORT = 8444;

/** Phones and tablets: offer front/back instead of a device list. */
const IS_MOBILE = typeof navigator !== "undefined" && /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);

/** Why the browser refuses camera access here, and the URL that fixes it. */
export function insecureContextMessage(): string {
  const host = window.location.hostname;
  return `Camera access needs a secure context. Open this console over HTTPS at https://${host}:${HTTPS_PORT}/ (opt-in TLS front door, see the README section "Browser camera from another device"), or on the device itself at http://localhost:8081/.`;
}

export type Facing = "user" | "environment";

/**
 * Browser webcam ingress for `browser_webrtc` cameras: capture getUserMedia
 * into a canvas and POST JPEG blobs to /stream/{id}/push at ~5 fps. The local
 * stream is shown in place of the MJPEG feed; the overlay still comes from SSE.
 */
export function useWebcamPush(cameraId: string | null) {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pushed, setPushed] = useState(0);
  const [failures, setFailures] = useState(0);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string>("");
  const [facing, setFacing] = useState<Facing>("environment");
  const secure = typeof window !== "undefined" ? window.isSecureContext : true;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const timer = useRef<number | null>(null);
  const inflight = useRef(false);

  /** List video inputs; labels are only filled in once the page has camera permission. */
  const loadDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      setDevices(all.filter((d) => d.kind === "videoinput"));
    } catch { /* permission not granted yet */ }
  }, []);
  useEffect(() => { if (cameraId && secure) void loadDevices(); }, [cameraId, secure, loadDevices]);

  const stop = useCallback(() => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
    setStream((s) => {
      s?.getTracks().forEach((t) => t.stop());
      return null;
    });
  }, []);

  const start = useCallback(async (pick?: { deviceId?: string; facing?: Facing }) => {
    if (!cameraId) return;
    setError(null);
    if (!window.isSecureContext) {
      setError(insecureContextMessage());
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser does not expose the camera API.");
      return;
    }
    const chosenId = pick?.deviceId ?? deviceId;
    const chosenFacing = pick?.facing ?? facing;
    try {
      setStream((prev) => { prev?.getTracks().forEach((t) => t.stop()); return null; });
      const video: MediaTrackConstraints = { width: { ideal: 1280 }, height: { ideal: 720 } };
      if (chosenId) video.deviceId = { exact: chosenId };
      else if (IS_MOBILE) video.facingMode = { ideal: chosenFacing };
      const s = await navigator.mediaDevices.getUserMedia({ video, audio: false });
      setStream(s);
      setPushed(0);
      setFailures(0);
      void loadDevices(); // labels become available once permission is granted
    } catch (err) {
      setError(err instanceof Error ? err.message : "Camera access denied");
    }
  }, [cameraId, deviceId, facing, loadDevices]);

  /** Switch to another camera while sharing (laptop device list or phone front/back). */
  const switchTo = useCallback(async (pick: { deviceId?: string; facing?: Facing }) => {
    if (pick.deviceId !== undefined) setDeviceId(pick.deviceId);
    if (pick.facing) setFacing(pick.facing);
    await start(pick);
  }, [start]);

  // Attach the stream to the preview element once both exist.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (stream) {
      v.srcObject = stream;
      void v.play().catch(() => undefined);
    } else {
      v.srcObject = null;
    }
  }, [stream]);

  // Pump frames.
  useEffect(() => {
    if (!stream || !cameraId) return;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    const url = api.stream.pushUrl(cameraId);
    const tick = () => {
      const v = videoRef.current;
      if (!v || !ctx || v.readyState < 2 || inflight.current) return;
      const vw = v.videoWidth;
      const vh = v.videoHeight;
      if (!vw || !vh) return;
      const scale = Math.min(1, MAX_WIDTH / vw);
      canvas.width = Math.round(vw * scale);
      canvas.height = Math.round(vh * scale);
      ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
      inflight.current = true;
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            inflight.current = false;
            return;
          }
          fetch(url, { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: blob })
            .then((res) => {
              if (res.ok) {
                setPushed((n) => n + 1);
                setError(null);
              } else {
                setFailures((n) => n + 1);
                if (res.status === 404) setError("Camera is not an enabled browser_webrtc camera (404).");
              }
            })
            .catch(() => setFailures((n) => n + 1))
            .finally(() => {
              inflight.current = false;
            });
        },
        "image/jpeg",
        0.8
      );
    };
    timer.current = window.setInterval(tick, 1000 / PUSH_FPS);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
      timer.current = null;
    };
  }, [stream, cameraId]);

  // Stop on unmount / camera change.
  useEffect(() => stop, [stop, cameraId]);

  return {
    videoRef, stream, active: !!stream, error, pushed, failures, start, stop,
    devices, deviceId, setDeviceId, facing, setFacing, switchTo, secure, isMobile: IS_MOBILE,
  };
}

export function WebcamControls({
  push,
}: {
  push: ReturnType<typeof useWebcamPush>;
}) {
  if (!push.secure) {
    return (
      <Notice kind="warn" className="text-xs flex items-start gap-2">
        <Lock className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        <span>{insecureContextMessage()}</span>
      </Notice>
    );
  }
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {push.isMobile ? (
        push.active ? (
          <Button size="sm" onClick={() => void push.switchTo({ facing: push.facing === "user" ? "environment" : "user", deviceId: "" })} title="Switch between front and back camera">
            <SwitchCamera className="h-3.5 w-3.5" /> Flip
          </Button>
        ) : (
          <Select value={push.facing} onChange={(e) => push.setFacing(e.target.value as Facing)} className="w-auto" aria-label="Camera">
            <option value="environment">Back camera</option>
            <option value="user">Front camera</option>
          </Select>
        )
      ) : push.devices.length > 0 && (
        <Select
          value={push.deviceId}
          onChange={(e) => (push.active ? void push.switchTo({ deviceId: e.target.value }) : push.setDeviceId(e.target.value))}
          className="w-auto max-w-[16rem]"
          aria-label="Camera"
        >
          <option value="">Default camera</option>
          {push.devices.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
        </Select>
      )}
      {push.active ? (
        <Button size="sm" variant="danger" onClick={push.stop}>
          <VideoOff className="h-3.5 w-3.5" /> Stop sharing
        </Button>
      ) : (
        <Button size="sm" variant="primary" onClick={() => void push.start()}>
          <Video className="h-3.5 w-3.5" /> Share camera
        </Button>
      )}
      {push.active && (
        <span className="text-xs text-muted-foreground tabular-nums">
          pushed {push.pushed} frames{push.failures ? ` · ${push.failures} failed` : ""} @ ~{PUSH_FPS} fps
        </span>
      )}
      {push.error && (
        <Notice kind="error" className="py-1 text-xs">
          {push.error}
        </Notice>
      )}
    </div>
  );
}
