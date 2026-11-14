import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Em dev, /api (REST e WebSocket) é repassado ao back-end: sem CORS e sem URL fixa no código.
// Use 127.0.0.1 (não "localhost"): no Node moderno, "localhost" pode resolver para ::1
// enquanto o uvicorn escuta em 127.0.0.1, causando ECONNREFUSED no proxy.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_PROXY_TARGET || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    server: { proxy: { "/api": { target, ws: true, changeOrigin: true } } },
  };
});
