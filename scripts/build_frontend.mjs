/**
 * Zero-dependency TypeScript compiler using Node.js native module.stripTypeScriptTypes.
 * Compiles frontend/src/types.ts + frontend/src/studio.ts -> app/static/studio.js.
 */
import fs from "node:fs";
import path from "node:path";
import { stripTypeScriptTypes } from "node:module";

const root = process.cwd();
const typesSrc = fs.readFileSync(path.join(root, "frontend/src/types.ts"), "utf-8");
const studioSrc = fs
  .readFileSync(path.join(root, "frontend/src/studio.ts"), "utf-8")
  .replace(/import\s+type\s+\{[\s\S]*?\}\s+from\s+["']\.\/types\.ts["'];?/g, "");

const combinedTs = `${typesSrc}\n${studioSrc}`;
const strippedJs = stripTypeScriptTypes(combinedTs, { mode: "strip" })
  .replace(/\bexport\s+(class|function|const|interface|type)\b/g, "$1");

const banner = `/* Generated from frontend/src/types.ts + frontend/src/studio.ts — DO NOT EDIT DIRECTLY */\n(function () {\n"use strict";\n`;
const footer = `\n})();\n`;

const outDir = path.join(root, "app/static");
fs.mkdirSync(outDir, { recursive: true });
const outFile = path.join(outDir, "studio.js");
fs.writeFileSync(outFile, banner + strippedJs.trim() + footer, "utf-8");
console.log(`Compiled TypeScript bundle -> ${path.relative(root, outFile)} (${fs.statSync(outFile).size} bytes)`);
