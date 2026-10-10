import { useCallback, useEffect, useRef, useState } from "react";
import { Video, VideoOff } from "lucide-react";
import { api } from "@/lib/api";
import { Button, Notice } from "./ui";

const PUSH_FPS = 5;
const MAX_WIDTH = 960;

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
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const timer = useRef<number | null>(null);
  const inflight = useRef(false);

  const stop = useCallback(() => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
    setStream((s) => {
      s?.getTracks().forEach((t) => t.stop());
      return null;
    });
  }, []);

  const start = useCallback(async () => {
    if (!cameraId) return;
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("getUserMedia is not available (requires HTTPS or localhost).");
      return;
    }
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      setStream(s);
      setPushed(0);
      setFailures(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Webcam access denied");
    }
  }, [cameraId]);

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

  return { videoRef, stream, active: !!stream, error, pushed, failures, start, stop };
}

export function WebcamControls({
  push,
}: {
  push: ReturnType<typeof useWebcamPush>;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {push.active ? (
        <Button size="sm" variant="danger" onClick={push.stop}>
          <VideoOff className="h-3.5 w-3.5" /> Stop sharing
        </Button>
      ) : (
        <Button size="sm" variant="primary" onClick={() => void push.start()}>
          <Video className="h-3.5 w-3.5" /> Share webcam
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
