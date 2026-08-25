#!/usr/bin/env python3
"""Build the title-named manuscript in an isolated local stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
TMP_ROOT = ROOT / "tmp" / "pdfs"
OUTPUT = PAPER / "Exact_Squarefree_Orbit_Sum_Reconstruction_of_Four_and_Five_Vertex_Loopless_Digraphs.pdf"
TOOLCHAIN_LOCK = ROOT / "PDF_BUILD_TOOLCHAIN.json"
IGNORED_SUFFIXES = {".aux", ".bbl", ".blg", ".fdb_latexmk", ".fls", ".log", ".out", ".toc", ".pdf"}
BUILD_ENVIRONMENT = {
    "FORCE_SOURCE_DATE": "1",
    "SOURCE_DATE_EPOCH": "1787529600",
    "TZ": "UTC",
}


def copy_sources(stage: Path) -> None:
    for source in PAPER.rglob("*"):
        relative = source.relative_to(PAPER)
        target = stage / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif source.suffix.lower() not in IGNORED_SUFFIXES:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    # This changes only the isolated diagnostic copy.  LaTeX's \listfiles
    # writes the loaded package inventory to main.log and has no page output.
    main = stage / "main.tex"
    source = main.read_text(encoding="utf-8")
    if "\\listfiles" not in source:
        main.write_text("\\listfiles\n" + source, encoding="utf-8", newline="\n")


def version_facts(executable: str, environment: dict[str, str]) -> dict[str, str]:
    result = subprocess.run(
        [executable, "--version"],
        env=environment,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"version query failed for {Path(executable).name}: {result.stderr}")
    stdout = result.stdout.replace("\r\n", "\n").strip()
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"empty version output for {Path(executable).name}")
    return {
        "executable": Path(executable).name.lower(),
        "banner": lines[0],
        "stdout_sha256": hashlib.sha256((stdout + "\n").encode("utf-8")).hexdigest(),
    }


def package_inventory(log: str) -> list[dict[str, str | None]]:
    match = re.search(r"\*File List\*\s*(.*?)\s*\*{5,}", log, flags=re.S)
    if match is None:
        raise RuntimeError("TeX log has no \\listfiles package inventory")
    rows = []
    for raw in match.group(1).splitlines():
        row = re.sub(r"\s+", " ", raw).strip()
        if not row:
            continue
        if re.match(r"^\S+\.\S+(?:\s|$)", row):
            rows.append(row)
        elif rows:
            rows[-1] += " " + row
        else:
            raise RuntimeError(f"malformed first TeX inventory row: {row!r}")
    if not rows:
        raise RuntimeError("TeX package inventory is empty")
    inventory = []
    for row in rows:
        name, _, remainder = row.partition(" ")
        version_match = re.match(
            r"(\d{4}[/-]\d{2}[/-]\d{2})(?:\s+((?:v|ver\.?\s*)?\S+))?",
            remainder,
            flags=re.I,
        )
        version = " ".join(part for part in version_match.groups() if part) if version_match else None
        inventory.append({"file": name, "version": version})
    return inventory


def normalized_commands(commands: list[list[str]]) -> list[list[str]]:
    return [[Path(command[0]).name.lower(), *command[1:]] for command in commands]


def pdflatex_commands(pdflatex: str, bibtex: str) -> list[list[str]]:
    latex = [
        pdflatex,
        "-no-shell-escape",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "main.tex",
    ]
    if "miktex" in str(Path(pdflatex)).lower():
        latex.insert(1, "--disable-installer")
    return [latex, [bibtex, "main"], latex, latex]


def compiler_commands(stage: Path) -> tuple[list[list[str]], str]:
    tectonic = os.environ.get("TECTONIC_EXE") or shutil.which("tectonic")
    if tectonic:
        options = [tectonic]
        if os.environ.get("TECTONIC_ONLY_CACHED") == "1":
            options.append("-C")
        options.extend(
            [
                "--untrusted",
                "--keep-logs",
                "--outdir",
                str(stage),
                "main.tex",
            ]
        )
        return ([options], "tectonic")
    explicit_pdflatex = os.environ.get("PDFLATEX_EXE")
    explicit_bibtex = os.environ.get("BIBTEX_EXE")
    if explicit_pdflatex and explicit_bibtex:
        return (pdflatex_commands(explicit_pdflatex, explicit_bibtex), "pdflatex+bibtex")

    # A MiKTeX installation can expose latexmk.exe even when its required
    # Perl runtime is absent. Prefer the self-contained direct sequence when
    # both underlying executables are available; latexmk remains a last-resort
    # wrapper for installations that configure their own engine discovery.
    pdflatex = shutil.which("pdflatex")
    bibtex = shutil.which("bibtex")
    if pdflatex and bibtex:
        return (pdflatex_commands(pdflatex, bibtex), "pdflatex+bibtex")

    latexmk = shutil.which("latexmk")
    if latexmk:
        return (
            [[
                latexmk,
                "-pdf",
                "-bibtex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "-pdflatex=pdflatex --disable-installer -no-shell-escape %O %S",
                "main.tex",
            ]],
            "latexmk",
        )
    raise FileNotFoundError("install Tectonic or a latexmk/pdflatex/bibtex toolchain")


def compile_isolated() -> tuple[bytes, str, dict[str, object]]:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(BUILD_ENVIRONMENT)

    with tempfile.TemporaryDirectory(prefix="public_build_", dir=TMP_ROOT) as raw_stage:
        stage = Path(raw_stage)
        copy_sources(stage)
        commands, compiler = compiler_commands(stage)
        engine = version_facts(commands[0][0], environment)
        bibliography = None
        if compiler == "pdflatex+bibtex":
            bibliography = version_facts(commands[1][0], environment)
        for index, command in enumerate(commands, start=1):
            result = subprocess.run(
                command,
                cwd=stage,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=300,
            )
            if result.returncode != 0:
                sys.stderr.write(result.stdout)
                sys.stderr.write(result.stderr)
                raise RuntimeError(f"{compiler} command {index} failed with exit code {result.returncode}")
        if not (stage / "main.pdf").is_file():
            raise RuntimeError(f"{compiler} did not produce main.pdf")
        log = (stage / "main.log").read_text(encoding="utf-8", errors="replace")
        forbidden = (
            "LaTeX Warning: There were undefined references",
            "undefined citations",
            "Missing character:",
            "Overfull \\hbox",
            "Overfull \\vbox",
            "! LaTeX Error:",
        )
        present = [needle for needle in forbidden if needle in log]
        if present:
            log_lines = log.splitlines()
            diagnostic_indexes = [
                index
                for index, line in enumerate(log_lines)
                if any(needle.lower() in line.lower() for needle in present)
                or line.startswith("LaTeX Warning: Reference")
            ]
            diagnostic_lines = []
            for index in diagnostic_indexes:
                diagnostic_lines.extend(log_lines[max(0, index - 4) : min(len(log_lines), index + 5)])
            raise RuntimeError(
                f"forbidden TeX diagnostics: {present}\n" + "\n".join(diagnostic_lines)
            )
        payload = (stage / "main.pdf").read_bytes()
        format_match = re.search(r"^LaTeX2e <[^>]+>(?: patch level \d+)?", log, flags=re.M)
        if format_match is None:
            raise RuntimeError("TeX log has no LaTeX format banner")
        inventory = package_inventory(log)
        toolchain = {
            "schema_version": "orbit_sum_pdf_build_toolchain_v1",
            "artifact": {
                "bytes": len(payload),
                "path": OUTPUT.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
            "canonical_environment": {
                "bibliography_processor": bibliography,
                "commands": normalized_commands(commands),
                "compiler_mode": compiler,
                "engine": engine,
                "environment": BUILD_ENVIRONMENT,
                "latex_format": format_match.group(0),
                "loaded_file_inventory": inventory,
                "network_package_installation": "disabled",
                "operating_system_family": platform.system(),
                "shell_escape": "disabled",
            },
            "assurance_boundary": {
                "canonical_environment_is_portable": False,
                "hosted_byte_identity_requires_observed_success": True,
                "lock_records_build_facts_not_a_publication_event": True,
            },
        }

    try:
        TMP_ROOT.rmdir()
        TMP_ROOT.parent.rmdir()
    except OSError:
        pass
    return payload, compiler, toolchain


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-byte-identical",
        action="store_true",
        help="compile in isolation and require byte identity with the tracked PDF without writing it",
    )
    parser.add_argument(
        "--write-toolchain-lock",
        action="store_true",
        help="write the canonical toolchain record only after a byte-identical isolated build",
    )
    parser.add_argument(
        "--check-toolchain-lock",
        action="store_true",
        help="require the observed compiler, commands, environment, and loaded-file inventory to match the lock",
    )
    args = parser.parse_args()
    payload, compiler, toolchain = compile_isolated()
    if args.write_toolchain_lock and not args.check_byte_identical:
        raise ValueError("--write-toolchain-lock requires --check-byte-identical")
    if args.check_toolchain_lock and not args.check_byte_identical:
        raise ValueError("--check-toolchain-lock requires --check-byte-identical")
    if args.check_byte_identical:
        if not OUTPUT.is_file():
            raise FileNotFoundError(f"missing distributed PDF: {OUTPUT}")
        expected = OUTPUT.read_bytes()
        if payload != expected:
            raise RuntimeError(
                "isolated source/PDF mismatch: "
                f"built={hashlib.sha256(payload).hexdigest()} "
                f"tracked={hashlib.sha256(expected).hexdigest()}"
            )
        if args.write_toolchain_lock:
            TOOLCHAIN_LOCK.write_text(
                json.dumps(toolchain, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        if args.check_toolchain_lock:
            if not TOOLCHAIN_LOCK.is_file():
                raise FileNotFoundError(f"missing toolchain lock: {TOOLCHAIN_LOCK}")
            expected_toolchain = json.loads(TOOLCHAIN_LOCK.read_text(encoding="utf-8"))
            if toolchain != expected_toolchain:
                raise RuntimeError(
                    "canonical toolchain mismatch: "
                    f"observed_engine={toolchain['canonical_environment']['engine']['banner']!r} "
                    f"locked_engine={expected_toolchain['canonical_environment']['engine']['banner']!r}"
                )
        print(
            "PASS_PAPER_BYTE_IDENTITY "
            f"compiler={compiler} sha256={hashlib.sha256(payload).hexdigest()} bytes={len(payload)} "
            f"toolchain_lock_written={args.write_toolchain_lock} "
            f"toolchain_lock_checked={args.check_toolchain_lock}"
        )
        return 0

    temporary = OUTPUT.with_suffix(".pdf.tmp")
    temporary.write_bytes(payload)
    temporary.replace(OUTPUT)
    print(
        f"PASS_PAPER_BUILD path={OUTPUT.relative_to(ROOT).as_posix()} "
        f"compiler={compiler} bytes={OUTPUT.stat().st_size}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"PAPER_BUILD_FAIL|{type(exc).__name__}|{exc}", file=sys.stderr)
        raise
