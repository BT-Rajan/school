import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://localhost:8000", ws: true } },
  },
  // The built app, for the offline browser test: the service worker runs only in builds.
  preview: { port: 4173, proxy: { "/api": { target: "http://localhost:8000", ws: true } } },
  build: { sourcemap: false },
  test: { environment: "jsdom", globals: false },
});
