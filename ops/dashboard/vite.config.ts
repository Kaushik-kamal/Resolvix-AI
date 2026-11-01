/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // loadEnv with an empty prefix also picks up plain process.env values such as VITE_PROXY_TARGET.
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_PROXY_TARGET || "http://localhost:8100";
  // Session cookies stay same-origin because the browser only talks to the Vite server; /v1 and /healthz are proxied.
  // proxyTimeout/timeout 0: GET /v1/stream is a long-lived connection.
  const proxy = {
    "/v1": {
      target,
      changeOrigin: true,
      proxyTimeout: 0,
      timeout: 0,
      configure: (p: { on: (event: "error", cb: (err: Error, req: unknown, res: unknown) => void) => void }) => {
        // If the API dies in the middle of an SSE stream the proxy would leave the browser connection open and
        // EventSource would never notice. Destroy the client socket so the dashboard starts its reconnect loop.
        p.on("error", (_err, _req, res) => {
          const r = res as { headersSent?: boolean; destroy?: () => void } | undefined;
          if (r?.headersSent) r.destroy?.();
        });
      },
    },
    "/healthz": { target, changeOrigin: true },
  };
  return {
    plugins: [react()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: { port: 5173, proxy },
    preview: { port: 5173, proxy },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
      css: false,
      testTimeout: 10000,
      hookTimeout: 10000,
    },
  };
});
