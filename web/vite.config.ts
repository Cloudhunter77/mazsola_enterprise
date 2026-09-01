import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // Recharts and React change far less often than app code; splitting them keeps
        // the cached vendor bundle out of every deploy, which matters on a phone
        // loading this over a VPN.
        manualChunks: { react: ["react", "react-dom", "react-router-dom"], charts: ["recharts"] },
      },
    },
  },
  server: {
    port: 5173,
    // In dev the SPA runs on Vite and the API on uvicorn; in production FastAPI
    // serves both from one origin, so app code always calls plain /api paths.
    proxy: { "/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000" },
  },
});
