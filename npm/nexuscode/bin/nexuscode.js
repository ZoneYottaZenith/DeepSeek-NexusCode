#!/usr/bin/env node
const { spawnSync } = require("node:child_process");

const arch = process.arch;
const plat = process.platform === "win32" ? "windows" : process.platform;
const pkg = `nexuscode-cli-${plat}-${arch}`;
const exe = `nexuscode${process.platform === "win32" ? ".exe" : ""}`;

let binary;
try {
  binary = require.resolve(`${pkg}/bin/${exe}`);
} catch {
  console.error(
    `nexuscode: no prebuilt binary for ${process.platform}-${process.arch}.\n` +
      `Install the matching optional package (${pkg}), or build from source:\n` +
      `  https://github.com/ZoneYottaZenith/DeepSeek-NexusCode`,
  );
  process.exit(1);
}

const res = spawnSync(binary, process.argv.slice(2), { stdio: "inherit" });
if (res.error) throw res.error;
process.exit(res.status === null ? 1 : res.status);
