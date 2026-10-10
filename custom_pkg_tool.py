"""
Manages the custom package PKGBUILDs.

Usage: python3 custom_pkg_tool.py <COMMAND> [OPTIONS]

Commands:
    validate   Check PKGBUILDs for correctness: they parse correctly, pass structural checks, and pass `namcap` audit.
    refresh    Check which packages are outdated against their upstream directive.
    update     Update outdated packages to their upstream version. Restores the PKGBUILD if update failed.

Options (all commands):
    -p, --package    Only this package. (can be repeated)
    -q, --quiet      Only print packages that have something to report.
    -h, --help       Show this message.

Options (validate):
    -b, --build      Build each package so namcap can audit `depends`.

Options (update):
    -n, --dry-run    Only print what would change, without making any changes.

Exit codes:
    0   Everything is valid and at the latest version.
    1   Error: a PKGBUILD does not parse, fails validation, trips namcap, has a broken upstream directive, or an
        update could not be applied.
    2   Warning: a package is outdated, has no upstream to check, or could not be looked up. Builds still succeed.

A run with both errors and warnings exits 1.
"""

# TODO: Check if an AppImage custom package's AppRun checks for DESKTOPINTEGRATION, and if the desktop entry sets it.

import argparse
import contextlib
import dataclasses
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

PACKAGES_DIR: Path = Path(__file__).resolve().parent / "packages"

EXIT_OK: int = 0
EXIT_ERROR: int = 1
EXIT_WARNING: int = 2

# Lines of `namcap --list` look like "elfpaths  : Check about ELF files ...".
NAMCAP_RULE_PATTERN: re.Pattern[str] = re.compile(r"^(\S+)\s+: ", re.MULTILINE)

HTTP_TIMEOUT: int = 30
USER_AGENT: str = "nosarch-packages-tool"

# Remote sources must be pinned. A local file shipped next to the PKGBUILD
# cannot change under us, so 'SKIP' is legitimate there.
REMOTE_SOURCE_PREFIXES: tuple[str, ...] = ("http://", "https://", "ftp://", "git+", "svn+", "hg+")

# Fields every custom package in this repo is expected to set.
REQUIRED_FIELDS: tuple[str, ...] = ("pkgdesc", "url", "license", "arch")

# namcap rules that cannot be satisfied by a repackaged vendor binary: every one of them reports a property of an
# upstream ELF we do not compile and cannot change. Rule names come from `namcap --list`.
NAMCAP_EXCLUDED_RULES: tuple[str, ...] = (
    "elfpaths",  # the payload lives under /opt by design
    "elfunstripped",
    "elfexecstack",
    "elfgnurelro",
    "elfnopie",
    "elfnoshstk",
    "elftextrel",
    "rpath",
    "runpath",
    "pydepends",  # a package that ships its own Python environment resolves every module it imports from it
    "javafiles",  # a vendored gem can ship a JRuby-only jar next to the Ruby it actually runs on
)


@dataclasses.dataclass(frozen=True, slots=True)
class Upstream:
    """Where to look up the current upstream version of a package."""

    kind: str
    url: str
    selector: str | None = None


@dataclasses.dataclass(slots=True)
class Result:
    """Outcome of checking a single package directory."""

    name: str
    current_version: str | None = None
    upstream_version: str | None = None
    problems: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)

    @property
    def outdated(self) -> bool:
        if self.current_version is None or self.upstream_version is None:
            return False
        return vercmp(self.current_version, self.upstream_version) < 0

    @property
    def has_errors(self) -> bool:
        """Whether this package would fail to build."""
        return bool(self.problems)

    @property
    def has_warnings(self) -> bool:
        """Whether this package still builds but has warnings."""
        return bool(self.warnings) or self.outdated


def vercmp(left: str, right: str) -> int:
    """Compares two versions the way pacman does. Negative if `left` is older."""
    try:
        completed: subprocess.CompletedProcess[str] = subprocess.run(
            ["vercmp", left, right], capture_output=True, text=True, check=True
        )
        return int(completed.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError):
        # Without vercmp the best available answer is "equal unless textually different".
        return 0 if left == right else -1


def _running_as_root() -> bool:
    return os.geteuid() == 0


def _drop_to_nobody() -> None:
    """
    `preexec_fn` that switches a subprocess from root to the `nobody` user.

    `makepkg` completely refuses to run as root, so an accidental `sudo` would otherwise fail on every package. The
    tool is meant to be run as a normal user, and `update` refuses root outright, but the reads and builds are better
    off degrading than hard-failing.
    """
    nobody = pwd.getpwnam("nobody")
    os.setgid(nobody.pw_gid)
    os.setuid(nobody.pw_uid)


@contextlib.contextmanager
def _buildable_copy(package_dir: Path) -> Iterator[Path]:
    """
    A directory `nobody` can read and write, containing this package's files.

    Only makes a copy when running as root. `nobody` cannot be trusted to read an arbitrary path in the repo
    (permissions, ACLs), but a non-root invocation already owns `package_dir` and can use it directly.
    """
    if not _running_as_root():
        yield package_dir
        return

    with tempfile.TemporaryDirectory(prefix="nosarch-pkg-tool-src-") as tmpdir:
        shutil.copytree(package_dir, tmpdir, dirs_exist_ok=True)

        mode = 0o777
        for root, dirs, files in os.walk(tmpdir):
            for name in dirs + files:
                os.chmod(os.path.join(root, name), mode)
        os.chmod(tmpdir, mode)

        yield Path(tmpdir)


def package_dirs(only: list[str]) -> list[Path]:
    """Every directory under `packages/` holding a PKGBUILD."""
    if not PACKAGES_DIR.is_dir():
        return []

    found: list[Path] = sorted(entry for entry in PACKAGES_DIR.iterdir() if (entry / "PKGBUILD").is_file())

    if only:
        found = [entry for entry in found if entry.name in only]

    return found


def read_srcinfo(package_dir: Path) -> dict[str, list[str]]:
    """
    Parses a PKGBUILD's metadata via `makepkg --printsrcinfo`.

    Values are collected per key, since keys such as `depends` and `sha256sums` can repeat.
    """
    with _buildable_copy(package_dir) as build_dir:
        completed: subprocess.CompletedProcess[str] = subprocess.run(
            ["makepkg", "--printsrcinfo"],
            cwd=build_dir,
            capture_output=True,
            text=True,
            check=True,
            preexec_fn=_drop_to_nobody if _running_as_root() else None,
        )

    fields: dict[str, list[str]] = {}

    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        fields.setdefault(key.strip(), []).append(value.strip())

    return fields


def read_upstream(package_dir: Path) -> Upstream | None:
    """Parses the `# nosarch-upstream:` directive from a PKGBUILD, if present."""
    match: re.Match[str] | None = re.compile(r"^#\s*nosarch-upstream:\s*(.+?)\s*$", re.MULTILINE).search(
        (package_dir / "PKGBUILD").read_text()
    )

    if match is None:
        return None

    parts: list[str] = match.group(1).split()

    if len(parts) < 2:
        return None

    kind: str = parts[0]

    if kind == "github":
        return Upstream(kind=kind, url=f"https://api.github.com/repos/{parts[1]}/releases/latest")

    if kind == "text":
        return Upstream(kind=kind, url=parts[1])

    if len(parts) < 3:
        return None

    return Upstream(kind=kind, url=parts[1], selector=" ".join(parts[2:]))


def fetch(url: str) -> str:
    """GETs a URL and returns the body as text."""
    request: urllib.request.Request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return response.read().decode()


def upstream_version(upstream: Upstream) -> str:
    """Resolves the current upstream version. Raises `ValueError` if it cannot."""
    body: str = fetch(upstream.url)

    if upstream.kind == "github":
        tag: Any = json.loads(body).get("tag_name")

        if not isinstance(tag, str):
            raise ValueError("release JSON has no 'tag_name'")

        return tag.lstrip("v")

    if upstream.kind == "json":
        assert upstream.selector is not None
        value: Any = json.loads(body)

        for key in upstream.selector.split("."):
            if not isinstance(value, dict) or key not in value:
                raise ValueError(f"JSON has no key '{upstream.selector}'")
            value = value[key]

        if not isinstance(value, (str, int, float)):
            raise ValueError(f"'{upstream.selector}' is not a scalar")

        return str(value)

    if upstream.kind == "text":
        # The body is a bare version string. Take the first line (strip surrounding whitespace).
        lines: list[str] = body.strip().splitlines()

        if not lines:
            raise ValueError("body is empty")

        return lines[0].strip()

    if upstream.kind == "regex":
        assert upstream.selector is not None
        match: re.Match[str] | None = re.search(upstream.selector, body)

        if match is None or not match.groups():
            raise ValueError(f"pattern '{upstream.selector}' matched nothing")

        return match.group(1)

    raise ValueError(f"unknown upstream kind '{upstream.kind}'")


def check_fields(package_dir: Path, fields: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """
    Structural checks that need neither the network nor a build.

    Returns (problems, warnings).
    """
    problems: list[str] = []
    warnings: list[str] = []

    names: list[str] = fields.get("pkgname", [])

    if package_dir.name not in names:
        problems.append(f"directory is named '{package_dir.name}' but PKGBUILD builds {names or ['nothing']}")

    for field in REQUIRED_FIELDS:
        if not fields.get(field):
            problems.append(f"missing '{field}'")

    sources: list[str] = fields.get("source", [])
    checksums: list[str] = []

    # Any of the supported digests is fine, but exactly one kind should be used.
    digests: list[str] = [key for key in fields if key.endswith("sums")]

    for key in digests:
        checksums.extend(fields[key])

    if sources and not digests:
        problems.append("sources are declared without any checksums")

    if len(digests) > 1:
        warnings.append(f"multiple checksum types declared: {', '.join(sorted(digests))}")

    if sources and checksums and len(sources) != len(checksums):
        problems.append(f"{len(sources)} source(s) but {len(checksums)} checksum(s)")

    for source, checksum in zip(sources, checksums):
        url: str = source.partition("::")[2] or source

        if checksum.upper() == "SKIP" and url.startswith(REMOTE_SOURCE_PREFIXES):
            problems.append(f"remote source is unpinned (checksum is SKIP): {url}")

        if url.startswith("http://"):
            warnings.append(f"source is fetched over plain HTTP: {url}")

    if "any" not in fields.get("arch", []) and not fields.get("pkgver"):
        problems.append("missing 'pkgver'")

    return problems, warnings


def namcap_rules() -> set[str]:
    """Every rule name namcap knows about, from `namcap --list`."""
    completed: subprocess.CompletedProcess[str] = subprocess.run(
        ["namcap", "--list"], capture_output=True, text=True, check=False
    )

    return {match.group(1) for match in NAMCAP_RULE_PATTERN.finditer(completed.stdout)}


def run_namcap(target: Path) -> list[str]:
    """Runs namcap against a PKGBUILD or a built package, minus the expected noise."""
    # namcap's own `--exclude` drops only the *last* rule in the list: it calls
    # `active_modules.update(modules)` inside the per-rule loop, re-adding
    # everything it just removed (see /usr/lib/python3*/site-packages/namcap.py).
    # `--rules` has no such bug, so select the complement instead.
    rules: set[str] = namcap_rules() - set(NAMCAP_EXCLUDED_RULES)

    if not rules:
        return ["could not determine namcap's rule list"]

    completed: subprocess.CompletedProcess[str] = subprocess.run(
        ["namcap", f"--rules={','.join(sorted(rules))}", str(target)], capture_output=True, text=True, check=False
    )

    findings: list[str] = []

    for line in completed.stdout.splitlines():
        stripped: str = line.strip()

        # namcap reports at three levels; only E is actionable here.
        if not stripped or " E: " not in stripped:
            continue

        # Every line is prefixed with the file namcap was given and the package
        # name, both of which the report header already shows.
        findings.append(f"namcap: {stripped.partition(' E: ')[2]}")

    return findings


def build_and_audit(package_dir: Path, quiet: bool = False) -> list[str]:
    """
    Builds the package into a scratch directory and runs namcap on the result.

    This is the only way to get namcap's `depends` analysis, which is what
    catches a PKGBUILD that under- or over-declares its dependencies.
    """
    if not quiet:
        print("    building (this can take a while)...", flush=True)

    with (
        _buildable_copy(package_dir) as build_dir,
        tempfile.TemporaryDirectory(prefix="nosarch-pkg-tool-out-") as scratch,
    ):
        # `nobody` needs write access to wherever the build writes output, same as the source copy above.
        if _running_as_root():
            os.chmod(scratch, 0o777)

        completed: subprocess.CompletedProcess[str] = subprocess.run(
            ["makepkg", "--force", "--clean", "--nodeps"],
            cwd=build_dir,
            capture_output=True,
            text=True,
            check=False,
            env={"PKGDEST": scratch, "SRCDEST": scratch, "BUILDDIR": scratch, "PATH": "/usr/bin", "HOME": scratch},
            preexec_fn=_drop_to_nobody if _running_as_root() else None,
        )

        if completed.returncode != 0:
            tail: str = "\n".join(completed.stderr.strip().splitlines()[-5:])
            return [f"build failed:\n{tail}"]

        built: list[Path] = sorted(Path(scratch).glob("*.pkg.tar.*"))

        if not built:
            return ["build produced no package file"]

        findings: list[str] = []

        for package_file in built:
            findings.extend(run_namcap(package_file))

        return findings


def validate_package(package_dir: Path, build: bool, have_namcap: bool, quiet: bool = False) -> Result:
    """Runs every enabled correctness check against one package directory."""
    result: Result = Result(name=package_dir.name)

    if not quiet:
        print("    parsing PKGBUILD...", flush=True)

    try:
        fields: dict[str, list[str]] = read_srcinfo(package_dir)
    except subprocess.CalledProcessError as error:
        tail: str = "\n".join(error.stderr.strip().splitlines()[-5:])
        result.problems.append(f"PKGBUILD does not parse:\n{tail}")
        return result
    except OSError:
        result.problems.append("could not run 'makepkg' (is pacman's base-devel installed?)")
        return result

    versions: list[str] = fields.get("pkgver", [])
    result.current_version = versions[0] if versions else None

    problems, warnings = check_fields(package_dir, fields)
    result.problems.extend(problems)
    result.warnings.extend(warnings)

    if have_namcap:
        if not quiet:
            print("    running namcap...", flush=True)
        result.problems.extend(run_namcap(package_dir / "PKGBUILD"))

        if build:
            result.problems.extend(build_and_audit(package_dir, quiet=quiet))

    return result


def refresh_package(package_dir: Path, quiet: bool = False) -> Result:
    """Compares one package's `pkgver` against its declared upstream."""
    result: Result = Result(name=package_dir.name)

    if not quiet:
        print("    parsing PKGBUILD...", flush=True)

    try:
        fields: dict[str, list[str]] = read_srcinfo(package_dir)
    except subprocess.CalledProcessError as error:
        tail: str = "\n".join(error.stderr.strip().splitlines()[-5:])
        result.problems.append(f"PKGBUILD does not parse:\n{tail}")
        return result
    except OSError:
        result.problems.append("could not run 'makepkg' (is pacman's base-devel installed?)")
        return result

    versions: list[str] = fields.get("pkgver", [])
    result.current_version = versions[0] if versions else None

    upstream: Upstream | None = read_upstream(package_dir)

    if upstream is None:
        result.warnings.append("no '# nosarch-upstream:' directive, cannot check freshness")
        return result

    if not quiet:
        print("    checking upstream version...", flush=True)

    try:
        result.upstream_version = upstream_version(upstream)
    except (urllib.error.URLError, OSError) as error:
        result.warnings.append(f"upstream lookup failed: {error}")
    except (ValueError, json.JSONDecodeError) as error:
        result.problems.append(f"upstream directive is broken: {error}")

    return result


# ---------------------------------------------------------------------------
# update helpers
# ---------------------------------------------------------------------------


def _pkgver(text: str) -> str | None:
    match: re.Match[str] | None = re.search(r"^pkgver=(\S+)$", text, flags=re.MULTILINE)
    return match.group(1) if match else None


def _set_field(text: str, key: str, value: str) -> str:
    updated, count = re.subn(rf"^{key}=\S+$", f"{key}={value}", text, count=1, flags=re.MULTILINE)
    return updated if count else text


def _tokenize(url: str) -> list[str]:
    return [token for token in re.split(r"[^0-9A-Za-z]+", url) if token]


def _flatten_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _flatten_strings(item)


def _pkgbuild_variables(text: str) -> dict[str, str]:
    """Simple top-level `_name=value` assignments, e.g. `_commit=abc123`."""
    variables: dict[str, str] = {}

    for match in re.finditer(r"^(?P<name>_\w+)=['\"]?(?P<value>[^'\"\s]+)['\"]?$", text, flags=re.MULTILINE):
        variables[match.group("name")] = match.group("value")

    return variables


def _sync_json_variables(
    text: str, fields: dict[str, list[str]], upstream: Upstream
) -> tuple[str, list[str], list[str]]:
    """
    Best-effort sync of extra variables (like `_commit`) a `json` endpoint embeds
    in its download URLs. Returns (new_text, synced, manual_notes).

    Each source URL the PKGBUILD evaluates to is matched against the URL fields of
    the endpoint response. A segment that changed between them is either a variable
    we can rewrite (`_name`'s old value was that segment) or something to do by hand.
    """
    try:
        data: Any = json.loads(fetch(upstream.url))
    except (urllib.error.URLError, OSError, ValueError) as error:
        return text, [], [f"could not re-fetch endpoint to sync extra variables: {error}"]

    new_urls: list[str] = [value for value in _flatten_strings(data) if value.startswith(("http://", "https://"))]

    if not new_urls:
        return text, [], []

    synced: list[str] = []
    manual: list[str] = []
    variables: dict[str, str] = _pkgbuild_variables(text)

    for source in fields.get("source", []):
        old_url: str = source.partition("::")[2] or source

        if not old_url.startswith(("http://", "https://")):
            continue

        old_tokens: list[str] = _tokenize(old_url)

        best: str | None = None
        best_score: int = 0

        for candidate in new_urls:
            score: int = sum(1 for old, new in zip(old_tokens, _tokenize(candidate)) if old == new)

            if score > best_score:
                best, best_score = candidate, score

        # Pair on host + at least a couple of path segments matching, else this is not
        # the same fetch. A pure prefix match (endpoint trims the file name off) needs no sync.
        if best is None or best_score < 4:
            continue

        for old, new in zip(old_tokens, _tokenize(best)):
            if old == new:
                continue

            name: str | None = next((n for n, value in variables.items() if value == old), None)

            if name is not None:
                text = re.sub(rf"^{name}=.*$", f"{name}={new}", text, count=1, flags=re.MULTILINE)
                variables[name] = new
                synced.append(f"{name}={new}")
            else:
                manual.append(f"URL segment '{old}' is now '{new}' but no variable holds the old value")

    return text, synced, manual


def _merge_checksums(before: str, after: str) -> str:
    """
    Keep `before`'s text but swap in the checksum values `updpkgsums` computed in
    `after`. updpkgsums rewrites the whole array in its own style; the repo pins each
    package's formatting instead.
    """
    block = re.compile(r"^\w*sums=\((?P<body>.*?)\)", re.DOTALL | re.MULTILINE)
    old_block = block.search(before)
    new_block = block.search(after)

    if old_block is None or new_block is None:
        return after

    old_entries: list[str] = re.findall(r"['\"]([^'\"]+)['\"]", old_block.group("body"))
    new_entries: list[str] = re.findall(r"['\"]([^'\"]+)['\"]", new_block.group("body"))

    if len(old_entries) != len(new_entries) or not old_entries:
        return after

    fresh: Iterator[str] = iter(new_entries)

    new_body: str = re.sub(
        r"(['\"])[^'\"]+\1", lambda m: m.group(1) + next(fresh) + m.group(1), old_block.group("body")
    )

    return before[: old_block.start("body")] + new_body + before[old_block.end("body") :]


def update_package(directory: Path, dry_run: bool, quiet: bool) -> str:
    """
    Outcome: "current" | "updated" | "skipped" | "needs-manual" | "failed".
    Prints its own progress and notes.
    """
    pkgbuild: Path = directory / "PKGBUILD"
    original: str = pkgbuild.read_text()

    upstream: Upstream | None = read_upstream(directory)

    if upstream is None:
        if not quiet:
            print("    no '# nosarch-upstream:' directive, skipping")
        return "skipped"

    try:
        upstream_ver: str = upstream_version(upstream)
    except (urllib.error.URLError, OSError) as error:
        print(f"    warning: upstream lookup failed: {error}")
        return "needs-manual"
    except (ValueError, json.JSONDecodeError) as error:
        print(f"    error: upstream directive is broken: {error}")
        return "failed"

    current: str | None = _pkgver(original)

    if current is None:
        print("    error: no 'pkgver=' line found")
        return "failed"

    if vercmp(current, upstream_ver) >= 0:
        if not quiet:
            print(f"    current at {current}")
        return "current"

    if not quiet:
        print(f"    {current} -> {upstream_ver}")

    if dry_run:
        print(f"    would set pkgver={upstream_ver}, reset pkgrel, refresh checksums")
        return "updated"

    # An endpoint may hand back a version with dashes (`2026.10.01-e373342`) while
    # pkgver carries dots (`2026.10.01.e373342`). Try the raw form first (it may be what
    # the URL templates expect), then the dotted form.
    candidates: list[str] = [upstream_ver]

    if "-" in upstream_ver:
        candidates.append(upstream_ver.replace("-", "."))

    last_error: str = "no candidate applied"

    for candidate in candidates:
        known_entries: set[str] = set(os.listdir(directory))
        text: str = _set_field(original, "pkgver", candidate)
        text = _set_field(text, "pkgrel", "1")
        pkgbuild.write_text(text)

        try:
            fields: dict[str, list[str]] = read_srcinfo(directory)
        except (subprocess.CalledProcessError, OSError) as error:
            last_error = f"PKGBUILD does not parse with pkgver={candidate}: {error}"
            continue

        if upstream.kind == "json":
            text, synced, manual = _sync_json_variables(text, fields, upstream)

            for note in manual:
                print(f"    note: {note}")

            if synced:
                if not quiet:
                    print(f"    synced extra variables: {', '.join(synced)}")
                pkgbuild.write_text(text)

                try:
                    fields = read_srcinfo(directory)
                except (subprocess.CalledProcessError, OSError) as error:
                    last_error = f"PKGBUILD does not parse after syncing variables: {error}"
                    continue

        sums: subprocess.CompletedProcess[str] = subprocess.run(
            ["updpkgsums"], cwd=directory, capture_output=True, text=True, check=False
        )

        # updpkgsums downloads sources into the package directory; they are cache, not files.
        for leftover in set(os.listdir(directory)) - known_entries - {"PKGBUILD"}:
            leftover_path: Path = directory / leftover

            if leftover_path.is_file():
                leftover_path.unlink()

        if sums.returncode != 0:
            tail: str = "\n".join(sums.stderr.strip().splitlines()[-5:])
            last_error = f"updpkgsums failed (the URL shape probably changed):\n{tail}"
            continue

        pkgbuild.write_text(_merge_checksums(text, pkgbuild.read_text()))

        return "updated"

    pkgbuild.write_text(original)
    print("    restored the original PKGBUILD")

    print(f"    error: {last_error}")
    return "failed"


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


def _print_result_block(result: Result, status: str, quiet: bool) -> None:
    if quiet and not (result.has_errors or result.has_warnings):
        return

    print(f"  {result.name:<28} {status}")

    for problem in result.problems:
        for line in problem.splitlines():
            print(f"      ERROR: {line}")

    for warning in result.warnings:
        print(f"      warning: {warning}")


def report_validate(results: list[Result], quiet: bool) -> None:
    for result in results:
        status: str = "INVALID" if result.problems else f"ok        {result.current_version}"
        _print_result_block(result, status, quiet)


def report_refresh(results: list[Result], quiet: bool) -> None:
    for result in results:
        if result.outdated:
            status: str = f"OUTDATED  {result.current_version} -> {result.upstream_version}"
        elif result.problems:
            status = "INVALID"
        elif result.upstream_version is not None:
            status = f"ok        {result.current_version} (current)"
        else:
            status = f"ok        {result.current_version}"

        _print_result_block(result, status, quiet)


def _exit_status(results: list[Result]) -> int:
    errored: list[Result] = [result for result in results if result.has_errors]
    warned: list[Result] = [result for result in results if result.has_warnings]

    # Errors outrank warnings: a package that cannot build matters more than a package that is only behind upstream.
    if errored:
        return EXIT_ERROR

    if warned:
        return EXIT_WARNING

    return EXIT_OK


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    directories: list[Path] = package_dirs(args.package)

    if not directories:
        if not args.quiet:
            print("[PACKAGES] No custom packages found.")
        return EXIT_OK

    have_namcap: bool = shutil.which("namcap") is not None

    if not args.quiet:
        if not have_namcap:
            print("[PACKAGES] WARNING: namcap is not installed, skipping PKGBUILD linting.")
            print("[PACKAGES]       Install it with: pacman -S namcap")
        elif not args.build:
            print("[PACKAGES] NOTE: pass --build to let namcap audit 'depends'.")

    results: list[Result] = []

    for index, directory in enumerate(directories, start=1):
        if not args.quiet:
            print(f"[PACKAGES] Checking {directory.name} ({index}/{len(directories)})...", flush=True)
        results.append(validate_package(directory, args.build, have_namcap, quiet=args.quiet))

    report_validate(results, args.quiet)

    errored: list[Result] = [result for result in results if result.has_errors]
    warned: list[Result] = [result for result in results if result.has_warnings]

    if errored:
        print(f"[PACKAGES] ERROR: {len(errored)} of {len(results)} custom package(s) will not build.")
    elif warned:
        print(f"[PACKAGES] WARNING: {len(warned)} of {len(results)} custom package(s) need attention.")
    elif not args.quiet:
        print("[PACKAGES] SUCCESS: All custom packages are valid.")

    return _exit_status(results)


def cmd_refresh(args: argparse.Namespace) -> int:
    directories: list[Path] = package_dirs(args.package)

    if not directories:
        if not args.quiet:
            print("[PACKAGES] No custom packages found.")
        return EXIT_OK

    results: list[Result] = []

    for index, directory in enumerate(directories, start=1):
        if not args.quiet:
            print(f"[PACKAGES] Checking {directory.name} ({index}/{len(directories)})...", flush=True)
        results.append(refresh_package(directory, quiet=args.quiet))

    report_refresh(results, args.quiet)

    outdated: list[Result] = [result for result in results if result.outdated]
    warned: list[Result] = [result for result in results if result.has_warnings]
    errored: list[Result] = [result for result in results if result.has_errors]

    if errored:
        print(f"[PACKAGES] ERROR: {len(errored)} of {len(results)} package(s) could not be validated.")
    elif outdated:
        print(f"[PACKAGES] WARNING: {len(outdated)} of {len(results)} package(s) are outdated.")
    elif warned:
        print(f"[PACKAGES] WARNING: {len(warned)} of {len(results)} package(s) need attention.")
    elif not args.quiet:
        print("[PACKAGES] SUCCESS: All custom packages are current.")

    return _exit_status(results)


def cmd_update(args: argparse.Namespace) -> int:
    if os.geteuid() == 0:
        print("[UPDATE] ERROR: run this as a normal user, not root. makepkg/updpkgsums refuse root,")
        print("         and a root edit would change PKGBUILD ownership under your repo.")
        return EXIT_ERROR

    for tool in ("makepkg", "updpkgsums"):
        if shutil.which(tool) is None:
            print(f"[UPDATE] ERROR: '{tool}' not found. Install base-devel and pacman-contrib.")
            return EXIT_ERROR

    directories: list[Path] = package_dirs(args.package)

    if not directories:
        if not args.quiet:
            print("[UPDATE] No custom packages found.")
        return EXIT_OK

    outcomes: dict[str, int] = {"current": 0, "updated": 0, "skipped": 0, "needs-manual": 0, "failed": 0}

    for index, directory in enumerate(directories, start=1):
        if not args.quiet:
            print(f"[UPDATE] Checking {directory.name} ({index}/{len(directories)})...", flush=True)

        outcome: str = update_package(directory, args.dry_run, args.quiet)
        outcomes[outcome] += 1

        if outcome == "updated":
            print(f"[UPDATE] {directory.name}: {'would update' if args.dry_run else 'updated'}")

    total: int = len(directories)

    if not args.quiet:
        parts: list[str] = []

        for key in ("updated", "current", "skipped", "needs-manual", "failed"):
            if outcomes[key]:
                parts.append(f"{outcomes[key]} {key}")

        print(f"[UPDATE] Done: {', '.join(parts)} out of {total} package(s).")

    if outcomes["failed"]:
        return EXIT_ERROR

    if outcomes["needs-manual"]:
        return EXIT_WARNING

    return EXIT_OK


def main() -> int:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="custom_pkg_tool.py",
        description="Validates, refreshes (checks for outdated), and updates the PKGBUILDs under packages/.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_shared(sub: argparse.ArgumentParser) -> None:
        _ = sub.add_argument("-p", "--package", action="append", default=[], help="only this package")
        _ = sub.add_argument(
            "-q", "--quiet", action="store_true", help="only print packages that have something to report"
        )

    validate_parser = subparsers.add_parser("validate", help="check PKGBUILDs for correctness")
    add_shared(validate_parser)
    _ = validate_parser.add_argument(
        "-b", "--build", action="store_true", help="build each package so namcap can audit depends"
    )

    refresh_parser = subparsers.add_parser("refresh", help="check which packages are outdated")
    add_shared(refresh_parser)

    update_parser = subparsers.add_parser("update", help="update outdated packages")
    add_shared(update_parser)
    _ = update_parser.add_argument(
        "-n", "--dry-run", action="store_true", help="print what would change, change nothing"
    )

    args: argparse.Namespace = parser.parse_args()

    if args.command == "validate":
        return cmd_validate(args)

    if args.command == "refresh":
        return cmd_refresh(args)

    return cmd_update(args)


if __name__ == "__main__":
    sys.exit(main())
