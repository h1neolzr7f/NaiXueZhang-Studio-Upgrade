import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { unlinkSync } from "node:fs";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "drop-vite-index-html",
      closeBundle() {
        try {
          unlinkSync(resolve(__dirname, "../web/app/index.html"));
        } catch {
          /* already absent */
        }
      },
    },
  ],
  base: "/assets/app/",
  build: {
    outDir: "../web/app",
    emptyOutDir: true,
    sourcemap: false,
    modulePreload: false,
    rollupOptions: {
      output: {
        entryFileNames: "workspace.js",
        chunkFileNames: "chunks/[name].js",
        assetFileNames: (info) => {
          const name = info.name || "";
          if (name.endsWith(".css")) return "workspace.css";
          return "assets/[name][extname]";
        },
      },
    },
  },
});
