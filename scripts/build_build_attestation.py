#!/usr/bin/env python3
"""Build the non-self-referential, event-free build attestation."""

from __future__ import annotations

import json
from pathlib import Path

import verify


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "MANIFEST_SHA256.txt"
OUTPUT = ROOT / "BUILD_ATTESTATION.json"


def main() -> int:
    if not MANIFEST.is_file():
        raise FileNotFoundError("build MANIFEST_SHA256.txt first")
    paper = verify.verify_pdf()
    visual_qa = verify.verify_visual_qa(paper)
    toolchain = verify.verify_toolchain_lock(paper)
    manifest = {
        "file_count": len(MANIFEST.read_text(encoding="utf-8").splitlines()),
        "sha256": verify.sha256(MANIFEST),
    }
    payload = verify.expected_attestation(manifest, paper, visual_qa, toolchain)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        "WROTE_BUILD_ATTESTATION "
        f"sha256={verify.sha256(OUTPUT)} pages={paper['pages']} "
        f"visual_qa={visual_qa['status']} toolchain_files={toolchain['loaded_file_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
