---
name: custom-package
description: Add a NosArch custom package (PKGBUILD under nosarch/packages). Use when asked to package an app, turn an
    AppImage, GitHub release, vendor tarball, or curl-pipe-bash installer into a package Decman can manage, or to add
    such a package to a module.
---

# Add custom package

Add a custom package to NosArch: a PKGBUILD in this repo that turns an AppImage, vendor tarball, or `curl | bash`
payload into an Arch package Decman can manage.

The source of truth for every step is `docs/internal/custom-packages.md` (repo root relative). Read it when a step
needs more than the summary below.

## Inputs

You need:

- The app's name (for example, "OpenChamber").
- Where the payload comes from: a GitHub release URL, a direct download URL, or an installer command.

If the name or the payload source is missing from the user's message, ask for it.

## Workflow

1. **Create the directory**: one directory per package under `nosarch/packages/`, named exactly as the `pkgname` it
   builds, suffixed with `-nosarch` to avoid AUR name collisions.
2. **Resolve and pin the payload**: find the actual file `package()` fetches and pin its `sha256sum`. For a
   `curl https://... | bash` installer, read the script with `less` to find the real URL(s) it fetches. Do not run
   the installer.
3. **Write the PKGBUILD**: `# Maintainer: NosArch` first line, the `# nosarch-upstream:` directive right after,
   then the package-info block (`pkgname`, `pkgdesc`, `pkgver`, `pkgrel`, `url`, `license`), then the build block
   (`arch`, `depends`, `provides`, `conflicts`, `options`, `source`, `sha256sums`), then functions as needed
   (`prepare()`, `build()`, `package()`).
4. **Declare upstream.** Add one `# nosarch-upstream:` directive so the version checker works:
   `github <owner>/<repo>` when the app has GitHub releases, otherwise `json`, then `text`, and `regex` only as a
   last resort (fragile).
5. **Validate**: run `python3 custom_pkg_tool.py validate --package <pkgname>`. Offer `--build` too so namcap
   audits `depends` (slower). Also check what the package would install: `pacman --query --list --file *.pkg.tar.zst`.

## Response style

Follow this output contract:

- One sentence stating what package was added and from what source.
- Then exactly these sections, in this order:
    - **Checks ran**: each command executed and its result.
    - **Follow-ups**: only what the user must still do (for example a root dry-run of decman).
      Omit the section when there is nothing to follow up on.
- Do not narrate the PKGBUILD line by line or restate the workflow steps back to the user.
