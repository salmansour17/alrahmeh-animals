// Vite builds the React app in frontend/ into static/dist, which Flask serves.
// static/dist is committed, so running the site never needs Node: only
// changing the frontend does.
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const fromRoot = (path) => fileURLToPath(new URL(path, import.meta.url));

export default defineConfig({
  plugins: [react()],
  root: fromRoot("./frontend"),
  build: {
    outDir: fromRoot("./static/dist"),
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` serves the frontend on its own port with hot reload and
    // sends API calls to the Flask app, so both run side by side.
    proxy: { "/api": "http://localhost:8000" },
  },
});
