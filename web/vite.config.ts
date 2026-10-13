// Local dev: `npm run dev` serves the app on http://localhost:5173 and
// forwards API calls to the API running on port 8000 (see web/README.md).
// Production: `npm run build` writes web/dist, which the API serves.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      ["/config", "/students", "/exercises", "/me", "/taxonomy", "/lessons", "/overview"].map((p) => [p, api]),
    ),
  },
});
