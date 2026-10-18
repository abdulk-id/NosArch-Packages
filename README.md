# NosArch Packages

PKGBUILDs for [NosArch](https://github.com/abdulk-id/NosArch)'s custom packages.

Custom packages let NosArch install an app as a pacman package. This covers apps with no Arch package, such as
AppImages, `curl https://... | bash` installers, and vendor tarballs.

A custom package is also how NosArch avoids the AUR. NosArch is moving its AUR dependencies into this repo, one package
at a time, until nothing it needs comes from the AUR anymore. `yay` is one of those: a core NosArch package that has no
Arch repository entry, so it is built here as `yay-nosarch` instead of being pulled from the AUR.

[PACKAGES.md](PACKAGES.md) documents how to add a package, how versions are tracked, and the traps worth knowing
before writing a PKGBUILD.

## Custom package tool

`custom_pkg_tool.py` validates, checks, and updates the PKGBUILDs:

```sh
python3 custom_pkg_tool.py validate      # parse and namcap audit
python3 custom_pkg_tool.py refresh       # check which packages are behind upstream
python3 custom_pkg_tool.py update        # update packages
```

Flags:

- `-p/--package` to manage a specific package.
- `-q/--quiet` to print only what needs attention.
- `validate` takes `-b/--build` to build each package so namcap can audit `depends` (slow).
- `update` takes `-n/--dry-run` to preview.

Exit codes are:

- `1` for errors that would fail a build (outranks warnings).
- `2` for warnings that would still build.

If [mise](https://mise.jdx.dev) is available, the same commands are available as tasks:

```sh
mise pkgchk    # validate
mise pkgref    # refresh
mise pkgupd    # update
```

`validate` and `refresh` need `base-devel` for `makepkg` and `namcap`, and `update` additionally needs
`pacman-contrib` for `updpkgsums`.

> NOTE: Do not run the tool as root.
