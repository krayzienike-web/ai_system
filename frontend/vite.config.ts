/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
  server: {
    host: true,
    proxy: { "/api": process.env.API_URL ?? "http://localhost:8000" },
  },
});
