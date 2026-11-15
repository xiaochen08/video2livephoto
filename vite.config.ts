import path from "node:path";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

/**
 * The renderer is built from the migrated Vue source tree. Electron loads the
 * generated file with loadFile(), so every asset URL must stay relative.
 */
export default defineConfig(({ mode }) => ({
  root: "src",
  base: "./",
  define: {
    __BUILD_TIME__: JSON.stringify(new Date().toISOString().slice(0, 16)),
  },
  plugins: [vue()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  build: {
    outDir: "../dist/renderer",
    emptyOutDir: true,
    sourcemap: mode === "development" ? "inline" : false,
    minify: mode !== "development",
  },
}));
