import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tier B build config. `public/` (including public/data/*.json emitted by the
// offline pipeline) is copied verbatim into `dist/` and served as static CDN
// assets — no function or backend in the request path.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 1200,
  },
});
