#!/usr/bin/env python3
"""Build the public SHA-256 manifest without self-reference cycles."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def windows_extended_path(path: Path) -> Path:
    resolved = str(path.resolve())
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return Path(resolved)
    if resolved.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + resolved[2:])
    return Path("\\\\?\\" + resolved)


ROOT = windows_extended_path(Path(__file__).resolve().parents[1])
MANIFEST = ROOT / "MANIFEST_SHA256.txt"
EXCLUDED_FILES = {
    "MANIFEST_SHA256.txt",
    "BUILD_ATTESTATION.json",
}
EXCLUDED_PARTS = {".git", "tmp", "__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".aux", ".bbl", ".blg", ".fdb_latexmk", ".fls", ".log", ".out", ".toc", ".pyc"}


def sha256(path: Path) -> str:
    state = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            state.update(block)
    return state.hexdigest()


def relative_name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def package_files() -> list[Path]:
    rows: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        rel = relative.as_posix()
        if rel in EXCLUDED_FILES:
            continue
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        rows.append(path)
    return sorted(rows, key=lambda item: item.relative_to(ROOT).as_posix())


def build() -> str:
    lines = [f"{sha256(path)}  {relative_name(path)}" for path in package_files()]
    return "\n".join(lines) + "\n"


def main() -> int:
    MANIFEST.write_text(build(), encoding="utf-8", newline="\n")
    print(f"WROTE_PUBLIC_MANIFEST files={len(package_files())} sha256={sha256(MANIFEST)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
