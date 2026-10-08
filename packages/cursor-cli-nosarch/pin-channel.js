"use strict";

// NosArch: pin Cursor CLI's release channel to `static` so a pacman-managed install never updates
// itself.
//
// `static` is upstream's channel for packaged installs. Every update path checks it before touching
// the network: the TUI's `/update` slash command, the background check a couple of seconds after
// startup, the `update` command, and the status `/about` reports.
//
// The channel lives in cli-config.json, resolved the way cursor-config/dist/paths.js does, and it
// stays out of that file until somebody picks one. So only fill it in when it is absent: a channel
// chosen with the hidden `agent set-channel` is the user's own call and is left alone.
//
// Any failure here is swallowed on purpose. The launcher runs this before every CLI start, and a
// config we cannot touch just means upstream behaviour, never a broken CLI.

const fs = require("fs");
const os = require("os");
const path = require("path");

const configDir = process.env.CURSOR_CONFIG_DIR;
const xdgConfigHome = process.env.XDG_CONFIG_HOME;
const dir =
    configDir && configDir.trim()
        ? configDir
        : xdgConfigHome && xdgConfigHome.trim()
          ? path.join(xdgConfigHome, "cursor")
          : path.join(os.homedir(), ".cursor");
const file = path.join(dir, "cli-config.json");

try {
    if (fs.existsSync(file)) {
        const config = JSON.parse(fs.readFileSync(file, "utf8"));
        if (config && typeof config === "object" && !Array.isArray(config) && !("channel" in config)) {
            fs.writeFileSync(file, `${JSON.stringify({ ...config, channel: "static" }, null, 2)}\n`);
        }
    } else {
        // The CLI merges its defaults into a partial file on first read and rewrites it whole, so a
        // file holding just the channel is enough to be picked up as `static`.
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(file, '{"channel": "static"}\n');
    }
} catch {
    // Unreadable HOME, or JSON that is not ours to repair: start the CLI and leave it to upstream.
}
