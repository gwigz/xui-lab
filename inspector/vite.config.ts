import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vitest/config";

const sourceRoot = fileURLToPath(new URL(".", import.meta.url));
const outputRoot = resolve(sourceRoot, "../xui_lab/_inspector");
const ignoredDirectories = new Set([
  "node_modules",
  "test-results",
  "playwright-report",
  "blob-report",
]);

function sourcePaths(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) {
        return ignoredDirectories.has(entry.name) ? [] : sourcePaths(path);
      }
      return [path];
    })
    .sort();
}

function sourceFingerprint(): string {
  const hash = createHash("sha256");
  for (const path of sourcePaths(sourceRoot)) {
    const relativePath = path.slice(sourceRoot.length).split("\\").join("/");
    hash.update(relativePath);
    hash.update("\0");
    hash.update(readFileSync(path));
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
