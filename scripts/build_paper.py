#!/usr/bin/env python3
"""Build the title-named manuscript in an isolated local stage."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
TMP_ROOT = ROOT / "tmp" / "pdfs"
OUTPUT = PAPER / "Exact_Squarefree_Orbit_Sum_Reconstruction_of_Four_and_Five_Vertex_Loopless_Digraphs.pdf"
IGNORED_SUFFIXES = {".aux", ".bbl", ".blg", ".fdb_latexmk", ".fls", ".log", ".out", ".toc", ".pdf"}


def copy_sources(stage: Path) -> None:
    for source in PAPER.rglob("*"):
        relative = source.relative_to(PAPER)
        target = stage / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif source.suffix.lower() not in IGNORED_SUFFIXES:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def pdflatex_commands(pdflatex: str, bibtex: str) -> list[list[str]]:
    latex = [
        pdflatex,
        "--disable-installer",
        "-no-shell-escape",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "main.tex",
    ]
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


def compile_isolated() -> tuple[bytes, str]:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = "1787529600"
    environment["FORCE_SOURCE_DATE"] = "1"
    environment["TZ"] = "UTC"

    with tempfile.TemporaryDirectory(prefix="public_build_", dir=TMP_ROOT) as raw_stage:
        stage = Path(raw_stage)
        copy_sources(stage)
        commands, compiler = compiler_commands(stage)
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

    try:
        TMP_ROOT.rmdir()
        TMP_ROOT.parent.rmdir()
    except OSError:
        pass
    return payload, compiler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-byte-identical",
        action="store_true",
        help="compile in isolation and require byte identity with the tracked PDF without writing it",
    )
    args = parser.parse_args()
    payload, compiler = compile_isolated()
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
        print(
            "PASS_PAPER_BYTE_IDENTITY "
            f"compiler={compiler} sha256={hashlib.sha256(payload).hexdigest()} bytes={len(payload)}"
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
