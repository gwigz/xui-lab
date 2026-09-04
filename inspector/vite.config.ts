import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vitest/config";

const sourceRoot = fileURLToPath(new URL(".", import.meta.url));
const outputRoot = resolve(sourceRoot, "../xui_lab/_inspector");
// The inputs the production bundle is built from. Keep in sync with
// xui_lab.inspector_assets.BUILD_INPUTS. Lint configuration, end-to-end
// tests, and unit tests never reach the bundle, so editing them must not
// report the embedded build as stale.
const buildInputs = [
  "index.html",
  "package-lock.json",
  "package.json",
  "src",
  "tsconfig.app.json",
  "tsconfig.json",
  "tsconfig.node.json",
  "vite.config.ts",
];
const testSuffixes = [".test.ts", ".test.tsx"];

function buildInputPaths(relativePath: string): string[] {
  const path = resolve(sourceRoot, relativePath);
  if (statSync(path).isDirectory()) {
    return readdirSync(path).flatMap((name) => buildInputPaths(`${relativePath}/${name}`));
  }
  return testSuffixes.some((suffix) => relativePath.endsWith(suffix)) ? [] : [relativePath];
}

function sourceFingerprint(): string {
  const hash = createHash("sha256");
  for (const relativePath of buildInputs.flatMap(buildInputPaths).sort()) {
    hash.update(relativePath);
    hash.update("\0");
    hash.update(readFileSync(resolve(sourceRoot, relativePath)));
    hash.update("\0");
  }
  return hash.digest("hex");
}

function fingerprintPlugin(): Plugin {
  const fingerprint = sourceFingerprint();
  return {
    name: "xui-lab-inspector-fingerprint",
    closeBundle() {
      writeFileSync(resolve(outputRoot, "source.sha256"), `${fingerprint}\n`);
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), fingerprintPlugin()],
  resolve: {
    alias: {
      "@": resolve(sourceRoot, "src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: process.env.VITE_INSPECTOR_API ?? "http://127.0.0.1:8765",
        timeout: 0,
        proxyTimeout: 0,
      },
    },
  },
  preview: {
    headers: {
      // Keep in sync with xui_lab.inspector_http.SECURITY_HEADERS. Do not add
      // unsafe-eval; Playwright preview must fail the same way FastAPI does.
      "Content-Security-Policy":
        "default-src 'self'; img-src 'self' blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'",
    },
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
  build: {
    outDir: outputRoot,
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
});
