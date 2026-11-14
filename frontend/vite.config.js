import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Em dev, /api (REST e WebSocket) é repassado ao back-end: sem CORS e sem URL fixa no código.
// O rewrite remove o /api, igual ao Caddy em produção (handle_path) — o backend
// sempre recebe as rotas sem prefixo (ex.: /leiloes).
const target = process.env.VITE_PROXY_TARGET || "http://localhost:8088";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    proxy: {
      "/api": {
        target,
        ws: true,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
