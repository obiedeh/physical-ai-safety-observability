import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Production: uvicorn (api/main.py) serves web/dist/index.html for "/" and
// "/ui/{path}" and mounts web/dist/assets at /assets, so the base stays "/".
// Dev: proxy the API prefixes to the FastAPI backend. UI routes live under /ui,
// which is not an API prefix, so no bypass logic is needed.
const apiTarget = process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8080";

const apiPrefixes = [
  "/config",
  "/models",
  "/stream",
  "/live",
  "/runtime",
  "/runs",
  "/events",
  "/incidents",
  "/feedback",
  "/metrics",
  "/health",
  "/cameras",
];

export default defineConfig({
  base: "/",
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 3000,
    proxy: Object.fromEntries(
      apiPrefixes.map((p) => [p, { target: apiTarget, changeOrigin: true }])
    ),
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
