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

// The website's Content-Security-Policy. Azure Storage cannot send headers, so
// it travels as a <meta> tag, the first element in <head>, and only in the
// production build: Vite's dev server injects inline scripts that a strict
// policy would block. The services' addresses are only known at deploy time,
// so the build leaves a placeholder that scripts/finalize-csp.mjs fills from
// config.js (cd.yml and docker-compose.yml run it after writing config.js).
//   script-src 'self': no inline scripts, and none are needed.
//   img-src data:: the stylesheet draws a paw pattern from a data: SVG.
//   No frame-ancestors, report-uri or sandbox: browsers ignore them in a meta tag.
const API = "__CSP_API_ORIGINS__";
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  `img-src 'self' data: ${API}`,
  "font-src 'self'",
  `connect-src 'self' ${API}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

function contentSecurityPolicy() {
  return {
    name: "content-security-policy",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler: (html) =>
        html.replace(
          "<head>",
          `<head>\n    <meta http-equiv="Content-Security-Policy" content="${CONTENT_SECURITY_POLICY}" />`,
        ),
    },
  };
}

export default defineConfig({
  plugins: [react(), contentSecurityPolicy()],
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
