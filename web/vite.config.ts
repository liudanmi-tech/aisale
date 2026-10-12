import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const api = process.env.VITE_API_PROXY || "http://127.0.0.1:8000";

export default defineConfig({
    plugins: [react()],
    resolve: { alias: { "@": resolve(__dirname, "src") } },
    build: {
        assetsDir: "static",
        chunkSizeWarningLimit: 1500,
        rollupOptions: {
            output: {
                manualChunks: (id) => (id.includes("node_modules/echarts") || id.includes("node_modules/zrender") ? "echarts" : undefined),
            },
        },
    },
    server: { proxy: { "/api": { target: api, ws: true, changeOrigin: true } } },
});
