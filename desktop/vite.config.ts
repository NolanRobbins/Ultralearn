import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The packaged app is served by FastAPI itself, so the build is relative and the
// dev server proxies to a locally running `ultralearn-api`.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.ULTRALEARN_API ?? "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
