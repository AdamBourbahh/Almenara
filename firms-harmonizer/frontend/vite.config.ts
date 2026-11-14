import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    host: true
  },
  preview: {
    port: 4173
  },
  build: {
    target: "es2022",
    sourcemap: true,
    chunkSizeWarningLimit: 2500,
    rollupOptions: {
      output: {
        // Keep the heavy GPU / map libraries in their own long-term cacheable chunks.
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("maplibre-gl") || id.includes("react-map-gl") || id.includes("@vis.gl/react-maplibre")) return "maplibre";
          if (id.includes("@deck.gl") || id.includes("@luma.gl") || id.includes("@loaders.gl") || id.includes("@math.gl")) return "deckgl";
          if (id.includes("h3-js")) return "h3";
          return "vendor";
        }
      }
    }
  },
  optimizeDeps: {
    include: ["maplibre-gl", "h3-js"]
  }
});
