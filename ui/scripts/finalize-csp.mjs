// Completes the website's Content-Security-Policy once the service addresses
// are known, and refuses to finish if anything is off.
//
//   node scripts/finalize-csp.mjs <built folder>      (e.g. dist)
//
// Why a step after the build: the site calls three services whose addresses
// are only known at deploy time (Terraform's outputs, written into config.js
// by cd.yml; docker-compose.yml writes its own for local runs). The build
// leaves a placeholder in the policy (vite.config.js); this fills it from
// config.js itself, so the allowed origins and the addresses the site really
// uses come from the same file and cannot disagree.
//
// It fails (exit 1) if: config.js holds an address that is not a plain
// http(s) origin, an HTML page lacks the policy or has more than one, the
// policy is not the first element in <head>, a placeholder is left, or an
// address in config.js is not allowed by connect-src and img-src.
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const PLACEHOLDER = "__CSP_API_ORIGINS__";
const ADDRESS_KEYS = ["animalsUrl", "donationsUrl", "enquiriesUrl"];
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);

function fail(message) {
  console.error(`finalize-csp: ${message}`);
  process.exit(1);
}

// The origins the site calls, from config.js. An empty address means "this
// same origin" (local development through Vite's proxy): nothing to add.
export function originsFrom(configJs) {
  const origins = new Set();
  for (const key of ADDRESS_KEYS) {
    const match = configJs.match(new RegExp(`${key}:\\s*"([^"]*)"`));
    if (!match) fail(`config.js has no ${key}`);
    if (!match[1]) continue;
    let url;
    try {
      url = new URL(match[1]);
    } catch {
      fail(`${key} in config.js is not an address: ${JSON.stringify(match[1])}`);
    }
    const secure = url.protocol === "https:";
    const local = url.protocol === "http:" && LOCAL_HOSTS.has(url.hostname);
    if (!secure && !local) fail(`${key} must be https (http only for localhost): ${url.origin}`);
    if (url.username || url.password) fail(`${key} must not carry a user or password`);
    origins.add(url.origin);
  }
  return [...origins].sort();
}

export function finalize(html, origins) {
  const metas = html.match(/<meta http-equiv="Content-Security-Policy"[^>]*>/g) ?? [];
  if (metas.length !== 1) fail(`expected one Content-Security-Policy meta tag, found ${metas.length}`);
  const firstInHead = /<head>\s*<meta http-equiv="Content-Security-Policy"/.test(html);
  if (!firstInHead) fail("the Content-Security-Policy meta tag must be the first element in <head>");
  if (!html.includes(PLACEHOLDER)) fail(`no ${PLACEHOLDER} placeholder: already finalized?`);
  const done = html.replaceAll(` ${PLACEHOLDER}`, origins.map((o) => ` ${o}`).join(""));
  if (done.includes(PLACEHOLDER)) fail("a placeholder is left after substitution");
  const policy = done.match(/<meta http-equiv="Content-Security-Policy" content="([^"]*)"/)[1];
  for (const directive of ["connect-src", "img-src"]) {
    const sources = (policy.split(";").map((d) => d.trim()).find((d) => d.startsWith(`${directive} `)) ?? "")
      .split(/\s+/)
      .slice(1);
    for (const origin of origins) {
      if (!sources.includes(origin)) fail(`${directive} does not allow ${origin}, which config.js uses`);
    }
  }
  return { html: done, policy };
}

if (import.meta.url === `file://${process.argv[1].replaceAll("\\", "/").replace(/^(?!\/)/, "/")}`) {
  const folder = process.argv[2] ?? fail("usage: node scripts/finalize-csp.mjs <built folder>");
  const origins = originsFrom(readFileSync(join(folder, "config.js"), "utf8"));
  const pages = readdirSync(folder).filter((name) => name.endsWith(".html"));
  if (pages.length === 0) fail(`no HTML page in ${folder}`);
  for (const page of pages) {
    const { html, policy } = finalize(readFileSync(join(folder, page), "utf8"), origins);
    writeFileSync(join(folder, page), html);
    console.log(`${page}: ${policy}`);
  }
}
