#!/usr/bin/env node
/*
 * Audit N-10 — fail CI if any dependency in ``frontend/package.json``
 * uses a caret (``^``) or tilde (``~``) version range. The committed
 * ``package-lock.json`` is the single source of truth for what
 * ``npm ci`` resolves to; a caret slipping into the manifest would
 * silently re-enable "compatible minor" upgrades on the next
 * lockfile-less install and defeat the lockfile's reproducibility
 * guarantee.
 *
 * Usage:
 *   node scripts/check-pinned-deps.cjs <path-to-package.json>
 *
 * Exits 0 if every dependency in every section is pinned; exits 1
 * (with a GitHub-flavoured ``::error`` annotation) otherwise.
 *
 * Local equivalents are useful: a pre-commit hook can call this with
 * the same argument and short-circuit a commit that introduces a
 * range.
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

const pkgArg = process.argv[2];
if (!pkgArg) {
  console.error("usage: check-pinned-deps.cjs <path-to-package.json>");
  process.exit(2);
}

const pkgPath = path.resolve(pkgArg);
let pkg;
try {
  pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
} catch (err) {
  console.error(`failed to read ${pkgPath}: ${err.message}`);
  process.exit(2);
}

const SECTIONS = [
  "dependencies",
  "devDependencies",
  "peerDependencies",
  "optionalDependencies",
];

const bad = [];
for (const section of SECTIONS) {
  const block = pkg[section];
  if (!block || typeof block !== "object") continue;
  for (const [name, version] of Object.entries(block)) {
    if (typeof version !== "string") continue;
    // ``file:`` / ``link:`` / ``git+`` / ``workspace:`` / ``npm:``
    // and plain version strings without a leading range operator
    // are all fine. Only ``^`` and ``~`` re-enable npm's
    // compatible-range upgrade behaviour.
    if (/^[\^~]/.test(version)) {
      bad.push({ section, name, version });
    }
  }
}

if (bad.length === 0) {
  console.log(`${pkgArg}: all versions are pinned (no ^/~ ranges).`);
  process.exit(0);
}

console.error(`${pkgArg} must use exact versions (no ^/~):`);
for (const { section, name, version } of bad) {
  console.error(`  ${section}.${name} = "${version}"`);
}
// GitHub-flavoured annotation so the failure shows up inline on the
// PR page next to ``package.json``.
console.error(
  `::error file=${pkgArg}::Caret/tilde version range found — pin to an exact version (audit N-10).`,
);
process.exit(1);
