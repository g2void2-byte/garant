import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
    // Vite 5+ blocks Host headers not in this allow-list when the dev
    // server is reached through a reverse-proxy / tunnel (e.g. when we
    // surface the TMA to Telegram via ``deploy expose``). ``true`` here
    // accepts every host — this is a *development-only* config and the
    // proxy itself enforces auth, so widening the allow-list does not
    // weaken anything that wasn't already wide-open in dev.
    allowedHosts: true,
    proxy: {
      // ``VITE_PROXY_TARGET`` lets compose / preview tunnels point
      // the proxy at the backend service hostname inside the docker
      // network (``http://backend:8080``) instead of the host's
      // ``localhost:8080``. Outside of compose the default keeps
      // working for ``npm run dev`` against ``uvicorn`` on the host.
      "/api": process.env.VITE_PROXY_TARGET || "http://localhost:8080",
      "/ws": {
        target: (process.env.VITE_PROXY_TARGET || "http://localhost:8080").replace(
          /^http/,
          "ws",
        ),
        ws: true,
      },
    },
  },
  build: {
    target: "es2020",
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query"],
          virtuoso: ["react-virtuoso"],
        },
      },
    },
  },
});
