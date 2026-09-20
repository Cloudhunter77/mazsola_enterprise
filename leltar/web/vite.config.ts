import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // React changes far less often than app code; splitting it keeps the cached
        // vendor bundle out of every deploy, which matters on a phone loading this
        // over a VPN.
        manualChunks: { react: ["react", "react-dom", "react-router-dom"] },
      },
    },
  },
  server: {
    // Not 5173: the receipt scanner's dev server already uses it, and both are run on
    // the same laptop.
    port: 5174,
    // In dev the SPA runs on Vite and the API on uvicorn; in production FastAPI serves
    // both from one origin, so app code always calls plain /api paths.
    proxy: { "/api": "http://127.0.0.1:8001", "/health": "http://127.0.0.1:8001" },
  },
});
