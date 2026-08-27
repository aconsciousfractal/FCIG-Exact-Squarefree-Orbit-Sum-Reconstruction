#!/usr/bin/env python3
"""Build the public structural-landscape certificate from finite data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import verify_structural_certificates as verifier


# Witness: solution index -> (component, K4 vertex, Q3 word).  The verifier
# re-enumerates the 128 covers and checks every adjacency against these labels.
A4_FACTOR_LABELS = [
    [0, 0, 0], [0, 0, 1], [0, 0, 2], [0, 0, 3],
    [0, 0, 4], [0, 0, 5], [0, 0, 6], [0, 0, 7],
    [1, 0, 0], [1, 0, 1], [1, 1, 0], [1, 1, 1],
    [1, 2, 0], [1, 2, 1], [1, 3, 0], [1, 3, 1],
    [2, 0, 0], [2, 0, 2], [2, 0, 4], [2, 0, 6],
    [1, 0, 4], [1, 0, 5], [2, 3, 0], [2, 3, 2],
    [2, 3, 4], [2, 3, 6], [1, 1, 4], [1, 1, 5],
    [1, 2, 4], [1, 2, 5], [1, 3, 4], [1, 3, 5],
    [2, 1, 0], [2, 2, 0], [2, 1, 2], [2, 2, 2],
    [2, 1, 4], [2, 2, 4], [2, 1, 6], [2, 2, 6],
    [3, 0, 0], [3, 0, 2], [3, 0, 4], [3, 0, 6],
    [1, 0, 2], [1, 0, 3], [3, 1, 0], [3, 1, 2],
    [3, 2, 0], [3, 3, 0], [3, 2, 2], [3, 3, 2],
    [1, 1, 2], [1, 1, 3], [3, 1, 4], [3, 1, 6],
    [1, 2, 2], [1, 2, 3], [1, 3, 2], [1, 3, 3],
    [3, 2, 4], [3, 3, 4], [3, 2, 6], [3, 3, 6],
    [3, 0, 1], [3, 0, 3], [3, 0, 5], [3, 0, 7],
    [2, 0, 1], [2, 0, 3], [2, 0, 5], [2, 0, 7],
    [0, 1, 0], [0, 1, 1], [0, 1, 2], [0, 1, 3],
    [0, 1, 4], [0, 1, 5], [0, 1, 6], [0, 1, 7],
    [1, 0, 6], [1, 0, 7], [2, 3, 1], [2, 3, 3],
    [2, 3, 5], [2, 3, 7], [0, 3, 0], [0, 3, 1],
    [0, 3, 2], [0, 3, 3], [0, 3, 4], [0, 3, 5],
    [0, 3, 6], [0, 3, 7], [3, 1, 1], [3, 1, 3],
    [3, 2, 1], [3, 3, 1], [3, 2, 3], [3, 3, 3],
    [1, 1, 6], [1, 1, 7], [3, 1, 5], [3, 1, 7],
    [1, 2, 6], [1, 2, 7], [1, 3, 6], [1, 3, 7],
    [3, 2, 5], [3, 3, 5], [3, 2, 7], [3, 3, 7],
    [2, 1, 1], [2, 2, 1], [2, 1, 3], [2, 2, 3],
    [0, 2, 0], [0, 2, 1], [0, 2, 2], [0, 2, 3],
    [0, 2, 4], [0, 2, 5], [0, 2, 6], [0, 2, 7],
    [2, 1, 5], [2, 2, 5], [2, 1, 7], [2, 2, 7],
]


# Componentwise K4 twists paired with the three cube translations.
A4_COMPONENT_K4_TWISTS = [
    [[0, 1, 2, 3], [0, 1, 2, 3], [2, 3, 0, 1]],
    [[0, 1, 2, 3], [0, 1, 2, 3], [2, 3, 0, 1]],
    [[2, 3, 0, 1], [0, 1, 2, 3], [0, 1, 2, 3]],
    [[1, 0, 3, 2], [0, 1, 2, 3], [0, 1, 2, 3]],
]


def build(root: Path, output: Path) -> dict[str, object]:
    payload = verifier.load_json(
        root / "certificates" / "five_vertex" / "canonical_payload.json"
    )
    family = verifier.load_json(
        root
        / "certificates"
        / "family_degree"
        / "structural"
        / "finite_theorem_certificate.json"
    )
    instance = verifier.load_json(
        root
        / "certificates"
        / "minimum_fingerprints"
        / "primary"
        / "instance.json"
    )
    matrix = (root / "certificates" / "structural" / "a5_signed_matrix.csv").read_bytes()
    certificate = verifier.build_certificate(
        payload,
        family,
        instance,
        matrix,
        A4_FACTOR_LABELS,
        A4_COMPONENT_K4_TWISTS,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(verifier.canonical_json_bytes(certificate))
    return certificate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    output = args.output or root / "certificates" / "structural" / "structural_certificate.json"
    try:
        certificate = build(root, output.resolve())
    except (OSError, KeyError, TypeError, ValueError, verifier.StructuralCertificateError) as error:
        print(f"STRUCTURAL_LANDSCAPE_BUILD_FAIL|{type(error).__name__}|{error}", file=sys.stderr)
        return 1
    print(
        "PASS_STRUCTURAL_LANDSCAPE_BUILD"
        f"|sha256={verifier.digest_bytes(verifier.canonical_json_bytes(certificate))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
