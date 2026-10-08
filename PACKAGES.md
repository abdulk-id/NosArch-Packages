# Packages

How packages in this repo are written, versioned, and checked.

## Layout

One directory per package under `packages/`, named exactly as the `pkgname` it builds.
Anything a `package()` function needs alongside the PKGBUILD ships in that directory.

The `-nosarch` suffix on every `pkgname` is deliberate. AUR helpers key off the name, so a package named `cursor`
would be recognized as the AUR's and could be replaced by it.

---

## Upstream Directives

Upstream directives tell the custom package tool how to find the current version of the app.

Add one `# nosarch-upstream:` directive near the top of the PKGBUILD:

```bash
# nosarch-upstream: github <owner>/<repo>
# nosarch-upstream: json https://example.com/api/latest version
# nosarch-upstream: text https://example.com/stable
# nosarch-upstream: regex https://example.com/download Example-([0-9.]+)-x86_64
```

| Name            | Form                      | Use when                                   |
| --------------- | ------------------------- | ------------------------------------------ |
| GitHub Releases | `github <owner>/<repo>`   | The app has GitHub releases                |
| JSON Endpoint   | `json <url> <dotted.key>` | The vendor has an update endpoint          |
| Raw Text        | `text <url>`              | The vendor publishes a bare version string |
| Regex           | `regex <url> <pattern>`   | Neither of the above                       |

The directive is optional. Without it the package is not version-checked.

### Regex directive

> `regex` is fragile and should be a last resort. `regex` scrapes a page meant for a browser, and any restyle can
> move or reword the surrounding text. Use `regex` only when a page is truly the only place the version is published.

The refresher fetches `<url>` as plain text (the raw HTML) and runs `<pattern>` against it as a Python regex. Whatever
the capture group `(...)` matches is treated as the current upstream version.

Example: a vendor's download page contains `href="/dl/Example-2.4.1-x86_64.AppImage"`. The directive
`# nosarch-upstream: regex https://example.com/download Example-([0-9.]+)-x86_64` matches that text and captures
`2.4.1`.

### What an update changes

Updating a PKGBUILD depends on the directive.

#### GitHub Releases

Release assets are at `https://github.com/<owner>/<repo>/releases/download/v$pkgver/<asset>`, so only `pkgver` changes.

#### JSON Endpoint

The endpoint usually returns more than the version, and the download URL may contain something besides it (a build
hash, a CDN path, a build number). Fetch the endpoint and compare its URL with the one in `source=()`:

```sh
curl --silent "<endpoint-url>" | python3 -m json.tool
```

Everything in the returned URL that is not the version has to be copied into the PKGBUILD as well.

> Example: Cursor (`cursor-desktop-nosarch`). Its endpoint returns:
>
> ```json
> {
>     "debUrl": "https://downloads.cursor.com/production/37076c6c.../linux/x64/deb/amd64/deb/cursor_3.22.7_amd64.deb",
>     "version": "3.22.7",
>     "commitSha": "37076c6c..."
> }
> ```
>
> The URL embeds the commit hash, so a bump sets `pkgver=3.22.7` and `_commit=<commitSha>`. Changing only `pkgver`
> builds `.../production/<old commit>/.../cursor_3.22.7_amd64.deb`, which doesn't exist, and the download fails.

#### Raw Text

The endpoint returns only the version. Read the vendor's installer script to see how it builds the download URL from
that version:

```sh
curl --location "<installer-url>" | less
```

If the script has changed (a new host, a new file name, a new architecture suffix, a new extra file), update
`source=()` to match before running `updpkgsums`. Re-read the script when the version jumps a major number.

> Example: Grok Build (`grok-build-nosarch`). `https://x.ai/cli/stable` returns `1.0.41`, and the binary lives at
> `https://x.ai/cli/grok-$pkgver-linux-x86_64`, so a bump is just `pkgver`.

Watch for sources that don't include the version.

> Example: Grok Build's `LICENSE` is fetched from the `main` branch, so its hash can change anytime.

When `updpkgsums` changes a hash for a file whose URL did not change, look at what changed in the file.

#### Regex

The regex gives you a version, but nothing about the URL. Open the page the directive scrapes and check that the
download link still has the shape `source=()` expects.

If `refresh` reports the lookup failed (exit `2`, "lookup failed") instead of a version, the page changed and the
pattern no longer matches. Fix the pattern first: open the raw HTML (`curl --location "<url>" | less`), find the new
text around the version, and update the directive. Then bump as usual.

## Self-updates

If a package updates itself on its own, block that as best-effort.

A common approach for CLI packages is a thin wrapper script that blocks update and uninstall commands with a message
that it is being managed by a pacman package.

---

## How To

### Add a package

#### 1. Create the directory

Under `packages/`, named exactly as the `pkgname` it will build, suffixed with `-nosarch`.

#### 2. Get the download URL and its checksum

The goal is to find the actual files `package()` needs to fetch, and pin each with a checksum.

- **AppImage or tarball**: the download URL is the artifact itself.

    ```sh
    curl --location --output example.AppImage "<url>"
    sha256sum example.AppImage
    ```

- **`curl https://... | bash` installer**: Read the installer script to find the URL(s) it fetches (a `.deb`, tarball,
  or binary), and pin those. If the script builds the URL from a version string, that version is what
  [upstream directive](#upstream-directives) needs to track.

    ```sh
    curl --location "<installer-url>" | less   # read it, don't run it
    curl --location --output example.tar.gz "<real-payload-url-found-in-script>"
    sha256sum example.tar.gz
    ```

Pin every hash so if the bytes at a pinned URL change, the build fails instead of installing something unexpected.

#### 3. Write the PKGBUILD

Writing style:

- `# Maintainer: NosArch` as the first line, with the `# nosarch-upstream:` directive
  ([Upstream Directives](#upstream-directives)) as the comment block right after it.
- Group the rest into two blocks, separated by a blank line:
    - Package info first, in this order: `pkgname`, `pkgdesc`, `pkgver`, `pkgrel`, `url`, `license`.
    - Build info second, in this order: `arch`, `depends`, `provides`, `conflicts`, `options`, `source`, `sha256sums`.
- Then the functions, in this order, as needed: `prepare()`, `build()`, `package()`.
- Always install the package's `LICENSE`/similar file under `/usr/share/licenses/$pkgname/`, even when `license=` is a
  standard SPDX identifier.
- Always install shell completions if the package offers them. Guard the generation with `|| true` and only install a
  completion file if it came out non-empty. Missing completions should not fail the build.

Match the existing PKGBUILDs.

Only add comments to explain non-standard behavior, and keep them concise. Obvious commands and behavior already
documented does not need comments (For example, if there are no shell completions, no need to comment saying so).

#### 4. Declare where upstream lives

Add the `# nosarch-upstream:` directive described in [Upstream Directives](#upstream-directives).

#### 5. Test it

1. Verify the PKGBUILD is valid: `python3 custom_pkg_tool.py validate --package <package-name>`
    - Pass `--build` so namcap can audit `depends` (slower process).
2. Check that the package actually installs to only the intended paths: `pacman --query --list --file *.pkg.tar.zst`

### Update a package

To update the PKGBUILDs:

```sh
python3 custom_pkg_tool.py update             # all packages
python3 custom_pkg_tool.py update -p <pkgname>
```

On failure it restores the PKGBUILD. `--dry-run` previews without changing anything.

Run `validate` (and `validate --build` for the full `depends` audit) and `refresh` afterwards to verify.

To do it manually:

1. Run `python3 custom_pkg_tool.py refresh` to see which packages are behind.
2. Set `pkgver` to that version and reset `pkgrel=1`.
3. Update any other variable `source=()` depend on (see [What an update changes](#what-an-update-changes)).
4. Refresh the checksums from inside the package directory: `cd packages/<pkgname> && updpkgsums`.
5. Run `python3 custom_pkg_tool.py validate --package <pkgname> --build` to make sure it still builds and passes
   namcap audit.

Only `pkgver`, `pkgrel`, the hashes, and whatever was changed in step 3 should have moved.

---

## Gotchas

- **Pin every remote source**: `SKIP` in the checksum is only for files shipped alongside the PKGBUILD. The tool
  treats `SKIP` on an `http(s)`/`git+` source as an error.
- **`LicenseRef-` requires installing the license**: A non-standard license identifier requires the license text under
  `/usr/share/licenses/$pkgname/`, or namcap fails the package. Vendor archives usually contain one. Install it.
- **Not every AppImage bundles a `.desktop` entry and icons**: Run `--appimage-extract` and check before assuming they
  are there. Also check that the desktop entry's `Icon=` name matches the icon files it ships.
- **A vendor that ships no license gets a pointer note**: When no license is published upstream, do not scrape pages
  for other documents (like ToS) to fake a license file. Declare `LicenseRef-<something>` (namcap rejects `custom`)
  and install a short README under `/usr/share/licenses/$pkgname/` that records the status.
    - Example: `devin-cli-nosarch`.
- **Expect namcap noise on repackaged binaries**: Unstripped ELFs, files outside FHS paths, and missing hardening flags
  are properties of a binary we did not compile. The tool already excludes those rules. Do not "fix" them.
- **An executable whose name ends in `.desktop` breaks `uwsm` launches**: `uwsm app` treats any argument ending in
  `.desktop` as a desktop entry file, so a launcher that passes the entry's `Exec` line verbatim makes uwsm parse the
  ELF as a `.desktop` file and fail. Point the installed desktop entries at a suffix-free `/usr/bin` symlink instead.
    - Example: `opencode-desktop-nosarch`. Upstream naming the binary `ai.opencode.desktop` caused such a problem.
