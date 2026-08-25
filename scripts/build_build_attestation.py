#!/usr/bin/env python3
"""Build the non-self-referential, event-free build attestation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "paper" / "Exact_Squarefree_Orbit_Sum_Reconstruction_of_Four_and_Five_Vertex_Loopless_Digraphs.pdf"
MANIFEST = ROOT / "MANIFEST_SHA256.txt"
OUTPUT = ROOT / "BUILD_ATTESTATION.json"


def sha256(path: Path) -> str:
    state = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            state.update(block)
    return state.hexdigest()


def main() -> int:
    if not PDF.is_file() or not MANIFEST.is_file():
        raise FileNotFoundError("build the PDF and manifest first")
    reader = PdfReader(str(PDF))
    payload = {
        "schema_version": "orbit_sum_build_attestation_v1",
        "artifact_kind": "versioned_release_build",
        "version": "2.0.0",
        "intended_release_tag": "v2.0.0",
        "author": {
            "name": "Oleksiy Babanskyy",
            "orcid": "0009-0001-6176-6208",
        },
        "repository": "https://github.com/aconsciousfractal/FCIG-Exact-Squarefree-Orbit-Sum-Reconstruction",
        "manifest": {
            "path": "MANIFEST_SHA256.txt",
            "file_count": len(MANIFEST.read_text(encoding="utf-8").splitlines()),
            "sha256": sha256(MANIFEST),
        },
        "paper": {
            "path": PDF.relative_to(ROOT).as_posix(),
            "bytes": PDF.stat().st_size,
            "pages": len(reader.pages),
            "sha256": sha256(PDF),
        },
        "mathematical_scope": {
            "n_values": [4, 5],
            "actions": ["S4", "A4", "S5", "A5"],
            "exact_reconstruction_degrees": [3, 3, 4, 4],
            "dictionary_sizes": [19, 29, 83, 124],
            "exact_global_minima": [7, 11, 14, 17],
            "minimum_domain": "subfamilies of the four declared cumulative squarefree support-orbit dictionaries",
        },
        "claim_contract": {
            "claim_boundary": "docs/PUBLIC_CLAIM_BOUNDARY.md",
            "license_boundary": "LICENSE_SCOPE.md",
            "third_party_full_texts_distributed": 0,
            "novelty_priority_firstness_claimed": False,
        },
        "event_boundary": {
            "external_review_state_recorded": False,
            "publication_state_recorded": False,
            "post_build_receipts": "external_to_versioned_source_tree",
        },
    }
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"WROTE_BUILD_ATTESTATION sha256={sha256(OUTPUT)} pages={len(reader.pages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
