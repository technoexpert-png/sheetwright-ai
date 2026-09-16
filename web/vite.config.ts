import { defineConfig } from "vite";
import type { ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The API is cookie-authenticated (httpOnly `sw_session`). Proxying the API
// prefixes through the dev server keeps every request same-origin in dev, so
// the session cookie travels without SameSite/CORS caveats.
const API_TARGET = process.env.SHEETWRIGHT_API ?? "http://localhost:8000";

// `/uploads` is both an API prefix and a client route (the history screen), so
// Only /api is proxied. Because every API route is namespaced there, it can
// never shadow a client-side route, so no Accept-header bypass is needed.
const api = (): ProxyOptions => ({
  target: API_TARGET,
  changeOrigin: true,
});

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": api() },
  },
});
