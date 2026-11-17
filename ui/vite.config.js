// Vite builds the website in this folder into ui/dist: plain HTML, CSS and JS
// that any static host can serve (an Azure Storage static website in
// production, nginx in Docker Compose). Node is a build tool only.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Where each service listens during local development. Override with
// environment variables if you run them on other ports.
const animals = process.env.ANIMALS_DEV_URL ?? "http://localhost:8001";
const donations = process.env.DONATIONS_DEV_URL ?? "http://localhost:8002";
const enquiries = process.env.ENQUIRIES_DEV_URL ?? "http://localhost:8003";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` serves the site on :5173 with hot reload. public/config.js
    // leaves the service addresses empty, so API calls stay on this origin and
    // these rules forward each one to the service that owns it.
    proxy: {
      "/api/animals": animals,
      "/api/requests": animals,
      "/api/donations": donations,
      "/api/enquiries": enquiries,
    },
  },
});
