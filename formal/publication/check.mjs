#!/usr/bin/env node
// Model-check the final.ply publication protocol. Usage:
//   node formal/publication/check.mjs            all checks
//   node formal/publication/check.mjs --trace    also print TLC's output, with the trace by which each rule catches its mutant
// Needs Java 11+. TLC comes from $TLA2TOOLS_JAR or is downloaded once into a
// per-user cache and verified against TLC_SHA256.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync, copyFileSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const TLC_URL = "https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar";
// The v1.8.0 tag is a rolling prerelease; this pins the build that was verified
// (TLC2 Version 2026.11.06.222357, rev d8fb231). Set OOOSPLAT_TLC_ANY=1 to accept another build.
const TLC_SHA256 = "e1f11b75c4b5bc4478ba0ac5cb6ae28e40a01b0016bc33e0aa97da22dfdbcd7f";
const showTrace = process.argv.includes("--trace");

function tlcJar() {
  const cacheRoot = process.env.LOCALAPPDATA ?? process.env.XDG_CACHE_HOME ?? join(homedir(), ".cache");
  const jar = process.env.TLA2TOOLS_JAR ?? join(cacheRoot, "ooosplat-formal", "tla2tools-1.8.0.jar");
  if (!existsSync(jar)) {
    mkdirSync(dirname(jar), { recursive: true });
    console.log(`Downloading TLC to ${jar}`);
    const r = spawnSync("curl", ["-sSfL", "-o", jar, TLC_URL], { stdio: "inherit" });
    if (r.status !== 0) throw new Error("TLC download failed; set TLA2TOOLS_JAR to a local tla2tools.jar");
  }
  const sha = createHash("sha256").update(readFileSync(jar)).digest("hex");
  if (sha !== TLC_SHA256 && process.env.OOOSPLAT_TLC_ANY !== "1") {
    throw new Error(`TLC jar ${jar} has sha256 ${sha}, expected ${TLC_SHA256}. Set OOOSPLAT_TLC_ANY=1 to use it anyway.`);
  }
  return jar;
}

const jar = tlcJar();
const work = mkdtempSync(join(tmpdir(), "ooosplat-tlc-"));
for (const f of ["Publication.tla", "Mutants.tla", "Publication.cfg", "ExternalEdit.cfg"]) copyFileSync(join(here, f), join(work, f));

function tlc(spec, cfgText, name) {
  writeFileSync(join(work, `${name}.cfg`), cfgText);
  const r = spawnSync("java", ["-XX:+UseParallelGC", "-cp", jar, "tlc2.TLC", "-workers", "auto",
    "-noGenerateSpecTE", "-metadir", join(work, `meta-${name}`), "-config", `${name}.cfg`, spec],
    { cwd: work, encoding: "utf8", maxBuffer: 1 << 28 });
  const out = r.stdout + r.stderr;
  const violated = [...out.matchAll(/Invariant (\w+) is violated/g)].map((m) => m[1]);
  const deadlock = /Deadlock reached/.test(out);
  const ok = /Model checking completed\. No error has been found/.test(out);
  const states = out.match(/(\d+) distinct states found/)?.[1];
  const parseError = !ok && violated.length === 0 && !deadlock;
  return { out, violated, deadlock, ok, states, parseError };
}

const base = readFileSync(join(here, "Publication.cfg"), "utf8");
let failures = 0;
const report = (good, msg, run) => {
  console.log(`${good ? "PASS" : "FAIL"}  ${msg}`);
  if (!good) failures++;
  if ((!good || showTrace) && run) console.log(run.out.split("\n").filter((l) => !/^(Parsing|Semantic|Linting)/.test(l)).join("\n"));
};

const outcome = (run) => run.ok ? `${run.states} states, no rule broken` : `broke ${run.violated.join(", ") || (run.deadlock ? "deadlock" : "TLC error")}`;

// 1. The protocol as the code implements it.
const main = tlc("Publication.tla", base, "main");
report(main.ok, `protocol holds: ${outcome(main)}`, main);

// 2. The same code when a committed final.ply is edited or deleted outside the app.
const external = readFileSync(join(here, "ExternalEdit.cfg"), "utf8");
const ext = tlc("Publication.tla", external, "external");
report(ext.ok, `task list loads after final.ply is changed outside the app: ${outcome(ext)}`, ext);

// 3. Each rule must catch a broken variant of the code it guards.
const mutants = [
  ["project.json Completed written before final.ply is installed", ["Prepare <- EarlyMeta_Prepare"], "ProjectCompletedIsReal"],
  ["transaction committed before final.ply is replaced", ["Prepare <- CommitFirst_Prepare", "Installed <- CommitFirst_Installed"], "CommittedOutputIntact"],
  ["finish marks the task Completed despite the runner's Err", ["Finish <- IgnoreErr_Finish"], "TaskCompletedIsReal"],
  ["load_locked skips reconcile_task_publication", ["BootStart <- NoBootReconcile_BootStart"], "StartupConverges"],
  ["load_locked returns the final.ply check's error instead of marking one task", ["BootStart <- PropagateErr_BootStart", "BootPubViews <- PropagateErr_BootPubViews"], "TaskListLoads", external],
];
for (const [what, overrides, rule, config = base] of mutants) {
  const cfg = config.replace("CONSTANTS", `CONSTANTS\n  ${overrides.join("\n  ")}`);
  const r = tlc("Mutants.tla", cfg, `mutant-${rule}`);
  report(r.violated.includes(rule), `${rule} catches: ${what}${r.violated.includes(rule) ? "" : ` (got: ${r.violated.join(", ") || (r.ok ? "no violation" : "TLC error")})`}`, r);
}

rmSync(work, { recursive: true, force: true });
console.log(failures ? `\n${failures} check(s) failed` : "\nAll checks passed");
process.exit(failures ? 1 : 0);
