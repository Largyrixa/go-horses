import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Em dev, os mesmos caminhos que o Caddy encaminha em produção são repassados ao
// back-end: /api (REST + WebSocket), /uploads (fotos enviadas), /static (imagens
// do seed) e /health. Assim o front usa sempre URLs relativas e não depende de
// host/porta nem de CORS — igual em `npm run dev` e atrás do Caddy na VM.
// Use 127.0.0.1 (não "localhost"): no Node moderno, "localhost" pode resolver
// para ::1 enquanto o uvicorn escuta em 127.0.0.1, causando ECONNREFUSED.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_PROXY_TARGET || "http://127.0.0.1:8088";

  const proxy = {
    "/api": { target, ws: true, changeOrigin: true },
    "/uploads": { target, changeOrigin: true },
    "/static": { target, changeOrigin: true },
    "/health": { target, changeOrigin: true },
  };

  return {
    plugins: [react()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: {
      host: "0.0.0.0",
      port: 8080,
      strictPort: true,
      proxy,
    },
    // `vite preview` serve o build de produção com as mesmas regras, em outra
    // porta para não brigar com o dev server (e com o Caddy, na VM).
    preview: { host: "0.0.0.0", port: 4173, strictPort: true, proxy },
  };
});
