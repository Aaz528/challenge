import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    /** Если 5173 занят — завершить с ошибкой, а не молча перейти на другой порт (иначе localhost:5173 может открыть «не тот» процесс). */
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
