import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const inspectorRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const schemaPath = resolve(inspectorRoot, "../schemas/inspector.openapi.json");
const generatedRoot = resolve(inspectorRoot, "src/generated");
const typesPath = resolve(generatedRoot, "inspector-api.ts");
const hashPath = resolve(generatedRoot, "openapi-hash.ts");
const check = process.argv.includes("--check");

function generate(outputRoot) {
  const outputTypes = resolve(outputRoot, "inspector-api.ts");
  const outputHash = resolve(outputRoot, "openapi-hash.ts");
  execFileSync(
    resolve(inspectorRoot, "node_modules/.bin/openapi-typescript"),
    [schemaPath, "-o", outputTypes],
    {
      stdio: "inherit",
    },
  );
  execFileSync(
    resolve(inspectorRoot, "node_modules/.bin/biome"),
    ["format", "--write", outputTypes],
    {
      stdio: "inherit",
    },
  );
  const digest = createHash("sha256").update(readFileSync(schemaPath)).digest("hex");
  writeFileSync(outputHash, `export const OPENAPI_HASH = "${digest}";\n`);
}

if (check) {
  const temporaryRoot = mkdtempSync(resolve(tmpdir(), "xui-lab-openapi-"));
  try {
    generate(temporaryRoot);
    for (const [actual, expected] of [
      [typesPath, resolve(temporaryRoot, "inspector-api.ts")],
      [hashPath, resolve(temporaryRoot, "openapi-hash.ts")],
    ]) {
      if (readFileSync(actual, "utf8") !== readFileSync(expected, "utf8")) {
        throw new Error(`${actual} is stale; run: npm run generate:api --prefix inspector`);
      }
    }
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
} else {
  generate(generatedRoot);
}
