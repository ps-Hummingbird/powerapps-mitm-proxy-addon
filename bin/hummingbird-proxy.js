#!/usr/bin/env node
"use strict";

const { spawn, spawnSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");

const PKG_ROOT = path.resolve(__dirname, "..");
const PY_SCRIPT = path.join(PKG_ROOT, "powerapp_dev_proxy.py");
const EXAMPLE_CONFIG = path.join(PKG_ROOT, "proxy.config.example.toml");
const DEFAULT_CONFIG = "proxy.config.toml";

function printHelp() {
  console.log(
    [
      "hummingbird-proxy - dev proxy for Dataverse / Dynamics 365 web resources and PCF controls",
      "",
      "Usage:",
      "  hummingbird-proxy [config-path] [-- mitmdump-args...]",
      "  hummingbird-proxy init [--force]",
      "",
      "Commands:",
      `  init          Copy the example config to ./${DEFAULT_CONFIG} in the current`,
      "                directory. Use --force to overwrite an existing file.",
      "",
      "Arguments:",
      `  config-path   Path to a TOML config file. Defaults to ./${DEFAULT_CONFIG}`,
      "                in the current working directory when omitted.",
      "",
      "Any extra arguments are forwarded to mitmdump, e.g.:",
      "  hummingbird-proxy ./proxy.config.jsonc -p 8888",
      "",
      "Prerequisite: mitmproxy must be installed and 'mitmdump' available on PATH.",
      "  https://www.mitmproxy.org/  (e.g. `pipx install mitmproxy`)",
    ].join("\n")
  );
}

function runInit(args) {
  const force = args.includes("--force") || args.includes("-f");
  const target = path.resolve(process.cwd(), DEFAULT_CONFIG);
  if (fs.existsSync(target) && !force) {
    console.error(`hummingbird-proxy: ${DEFAULT_CONFIG} already exists: ${target}`);
    console.error("Use `hummingbird-proxy init --force` to overwrite it.");
    process.exit(1);
  }
  fs.copyFileSync(EXAMPLE_CONFIG, target);
  console.log(`Created ${target}`);
  addProxyScript(force);
  console.log("Edit the rules, then run `npm run proxy` from this directory.");
}

function addProxyScript(force) {
  const pkgPath = path.resolve(process.cwd(), "package.json");
  if (!fs.existsSync(pkgPath)) {
    console.warn(
      "hummingbird-proxy: no package.json found; skipped adding the `proxy` script."
    );
    return;
  }
  let pkg;
  try {
    pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
  } catch (err) {
    console.warn(`hummingbird-proxy: could not parse package.json (${err.message}); skipped adding the \`proxy\` script.`);
    return;
  }
  pkg.scripts = pkg.scripts || {};
  if (pkg.scripts.proxy && !force) {
    console.warn(
      `hummingbird-proxy: a \`proxy\` script already exists (${pkg.scripts.proxy}); left unchanged.`
    );
    return;
  }
  pkg.scripts.proxy = "hummingbird-proxy";
  fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + "\n");
  console.log(`Added \`proxy\` script to ${pkgPath}`);
}

function hasMitmdump() {
  const probe = process.platform === "win32" ? "where" : "which";
  const res = spawnSync(probe, ["mitmdump"], { stdio: "ignore" });
  return res.status === 0;
}

function main() {
  const argv = process.argv.slice(2);
  if (argv.includes("-h") || argv.includes("--help")) {
    printHelp();
    return;
  }

  if (argv[0] === "init") {
    runInit(argv.slice(1));
    return;
  }

  // Only the first token can be the config path, and only when it isn't a
  // flag; everything else is forwarded to mitmdump so a flag's value (e.g. the
  // `8888` in `-p 8888`) is never mistaken for the config path.
  let configArg;
  let passthrough;
  if (argv.length > 0 && !argv[0].startsWith("-")) {
    configArg = argv[0];
    passthrough = argv.slice(1);
  } else {
    passthrough = argv.slice();
  }
  // Drop a leading `--` separator; the rest already goes to mitmdump.
  if (passthrough[0] === "--") {
    passthrough.shift();
  }

  const configPath = path.resolve(process.cwd(), configArg || DEFAULT_CONFIG);
  if (!fs.existsSync(configPath)) {
    console.error(`hummingbird-proxy: config file not found: ${configPath}`);
    console.error(
      configArg
        ? "Check the path you passed."
        : `Create a ${DEFAULT_CONFIG} in this directory, or pass a path: hummingbird-proxy ./path/to/${DEFAULT_CONFIG}`
    );
    process.exit(1);
  }

  if (!hasMitmdump()) {
    console.error("hummingbird-proxy: 'mitmdump' was not found on your PATH.");
    console.error(
      "mitmproxy is required. Install it from https://www.mitmproxy.org/ (e.g. `pipx install mitmproxy`)."
    );
    process.exit(1);
  }

  const args = ["-s", PY_SCRIPT, ...passthrough];
  const child = spawn("mitmdump", args, {
    stdio: "inherit",
    env: { ...process.env, HUMMINGBIRD_PROXY_CONFIG: configPath },
  });

  child.on("error", (err) => {
    console.error(`hummingbird-proxy: failed to start mitmdump: ${err.message}`);
    process.exit(1);
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
    } else {
      process.exit(code ?? 0);
    }
  });
}

main();
