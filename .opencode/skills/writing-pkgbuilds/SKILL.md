---
name: writing-pkgbuilds
description: Write a PKGBUILD following NosArch's styling. Use when asked to write or edit a PKGBUILD for a custom package.
---

# Writing PKGBUILDs

Writing style:

- `# Maintainer: NosArch` as the first line.
- The `# nosarch-upstream:` directive ([Upstream Directives](PACKAGES.md#upstream-directives)) right after the blank line after
  the maintainer line.
- Variables:
    - Package vars first, in this order: `pkgname`, `pkgdesc`, `pkgver`, `pkgrel`, `url`, `license`.
    - Build vars second, in this order:
        - `arch`,
        - `depends`,
        - `optdepends` (if any),
        - `makedepends` (if any),
        - `checkdepends` (if any),
        - `options`,
        - `provides`,
        - `conflicts` (if any),
        - `source`,
        - `sha256sums`
- Then the functions, in this order, as needed:
    - `prepare()` - Pre-processing, such as unpacking sources, applying patches etc.
    - `build()` - Building the binaries/executables.
    - `check()` - Running tests.
    - `package()` - Installing files into the packaging directory.
- Order of actions performed by `package()`:
    1. Install the binaries/executables.
    2. Install the self-update block if any.
    3. Install the `.desktop` entry and icons.
    4. Install the shell completion files if any.
    5. Install manpages of the package if any.
    6. Lastly install the package's license and similar files (for example `THIRD-PARTY-NOTICES).
- When adding a self-update blocking measure, add comments above it in the following format:

```sh
# Self-update block:
# [1-3 line explanation of the self-update blocking measure]
```

- When installing files written by us that are longer (>13 lines), write a separate file in the package's directory,
  instead of writing in place with `install ... /dev/stdin /path/file/installed/to <<'EOF'` in the PKGBUILD.
- Only add comments to explain non-standard behavior, and keep them concise. Obvious commands and behavior already
  documented does not need comments (For example, if there are no shell completions, no need to add a comment saying
  so).
