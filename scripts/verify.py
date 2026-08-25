#!/usr/bin/env python3
"""Aggregate verifier for the unified four/five-vertex paper and atlas."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

import build_manifest


def windows_extended_path(path: Path) -> Path:
    resolved = str(path.resolve())
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return Path(resolved)
    if resolved.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + resolved[2:])
    return Path("\\\\?\\" + resolved)


def comparable_path(path: Path) -> str:
    rendered = str(regular_windows_path(path).resolve())
    return os.path.normcase(os.path.normpath(rendered))


def regular_windows_path(path: Path) -> Path:
    rendered = str(path.resolve())
    if os.name == "nt" and rendered.startswith("\\\\?\\UNC\\"):
        rendered = "\\\\" + rendered[8:]
    elif os.name == "nt" and rendered.startswith("\\\\?\\"):
        rendered = rendered[4:]
    return Path(rendered)


ROOT = windows_extended_path(Path(__file__).resolve().parents[1])
ORBIT_ATLAS = ROOT / "certificates" / "orbit_atlas"
MINIMUM = ROOT / "certificates" / "minimum_fingerprints"
FAMILY = ROOT / "certificates" / "family_degree"
FIVE_VERTEX_SCRIPTS = ROOT / "scripts" / "five_vertex"
N5_DATA = ROOT / "certificates" / "five_vertex"
PDF = ROOT / "paper" / "Exact_Squarefree_Orbit_Sum_Reconstruction_of_Four_and_Five_Vertex_Loopless_Digraphs.pdf"
ATTESTATION = ROOT / "BUILD_ATTESTATION.json"
THEOREM_SUMMARY = ROOT / "certificates" / "theorem_summary.json"
CASE_ORDER = ("S4", "A4", "S5", "A5")
PACKAGE_VERSION = "2.0.0"
RELEASE_TAG = "v2.0.0"
# n, degree, dictionary, minimum, patterns, residual, tree-separated,
# tree-blind, lower-DAG nodes, conditional minimum, conditional solution count
EXPECTED_CASE_ROWS = {
    "S4": (4, 3, 19, 7, 218, 39, 39, 0, 11, 2, 2),
    "A4": (4, 3, 29, 11, 368, 51, 51, 0, 22, 4, 128),
    "S5": (5, 4, 83, 14, 9608, 190, 190, 0, 63589, 4, 2),
    "A5": (5, 4, 124, 17, 17824, 113, 105, 8, 213648, 4, 200),
}
ALLOWED_UNMANIFESTED_TRACKED = {"MANIFEST_SHA256.txt", "BUILD_ATTESTATION.json"}
ORBIT_ATLAS_SCIENTIFIC = (
    "coordinate_registry.json",
    "pattern_registry.json",
    "quadratic_collision_atlas.json",
    "cubic_witness_map.json",
    "conditional_minimum_extensions.json",
    "normalized_coordinate_registry.csv",
    "normalized_pattern_registry.csv",
    "normalized_quadratic_collision_atlas.csv",
    "normalized_cubic_witness_map.csv",
    "normalized_conditional_minimum_extensions.csv",
)
ALLOWED_PUBLIC_FOUR_TUPLES = {
    (1, 5, 16, 61),
    (1, 6, 21, 96),
    (2, 4, 4, 4),
    (3, 3, 4, 4),
    (6, 8, 22, 28),
    (7, 11, 14, 17),
    (8, 12, 26, 32),
    (8, 12, 27, 41),
    (17, 12, 4, 1),
    (19, 29, 83, 124),
    (39, 51, 190, 105),
    (39, 51, 190, 113),
    (218, 368, 9608, 17824),
}


def expected_theorem_summary() -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for action, row in EXPECTED_CASE_ROWS.items():
        (
            n,
            degree,
            dictionary,
            minimum,
            patterns,
            residual,
            tree_separated,
            tree_blind,
            dag_nodes,
            conditional_minimum,
            conditional_count,
        ) = row
        cases[action] = {
            "n": n,
            "action": action,
            "reconstruction_degree": degree,
            "dictionary_size": dictionary,
            "global_minimum": minimum,
            "pattern_orbits": patterns,
            "residual_pairs_before_top_degree": residual,
            "tree_separated_pairs": tree_separated,
            "tree_blind_pairs": tree_blind,
            "lower_dag_nodes": dag_nodes,
            "conditional_extension_minimum": conditional_minimum,
            "conditional_extension_solution_count": conditional_count,
        }
    return {
        "schema_version": "orbit_sum_theorem_summary_v1",
        "carrier": "Boolean loopless directed graphs on the ordered-pair carrier",
        "minimum_domain": "subfamilies of the four declared cumulative squarefree support-orbit dictionaries",
        "case_order": list(CASE_ORDER),
        "cases": cases,
        "scope_ceiling": {
            "n_values": [4, 5],
            "arbitrary_invariants": False,
            "chemical_interpretation": False,
            "physical_chirality": False,
            "novelty_priority_firstness": False,
        },
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    state = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            state.update(block)
    return state.hexdigest()


def parse_strict_json_object(raw: bytes, source: str = "<memory>") -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            require(key not in value, f"duplicate JSON key {key!r}: {source}")
            value[key] = item
        return value

    text = raw.decode("utf-8", errors="strict")
    value = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    require(isinstance(value, dict), f"JSON root is not an object: {source}")
    return value


def load_json(path: Path) -> dict[str, Any]:
    return parse_strict_json_object(path.read_bytes(), str(path))


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def pretty_canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def group_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload["groups"]
    if isinstance(rows, dict):
        return rows
    return {str(row["group"]): row for row in rows}


def python_command(script: Path, *arguments: str) -> list[str]:
    command = [sys.executable, "-B"]
    if not __debug__:
        command.append("-O")
    command.extend([str(script), *arguments])
    return command


def run(command: list[str], *, cwd: Path = ROOT, timeout: int = 900, input_text: str | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        input=input_text,
    )
    require(
        result.returncode == 0,
        f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}\n{result.stderr}",
    )
    return result.stdout


def verify_manifest() -> dict[str, Any]:
    manifest = ROOT / "MANIFEST_SHA256.txt"
    require(manifest.is_file(), "missing MANIFEST_SHA256.txt")
    observed: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        require(match is not None, f"invalid manifest line: {line!r}")
        digest, relative = match.groups()
        require(relative not in observed, f"duplicate manifest path: {relative}")
        require("\\" not in relative and not relative.startswith("/"), f"nonportable manifest path: {relative}")
        observed[relative] = digest
    expected_paths = {build_manifest.relative_name(path) for path in build_manifest.package_files()}
    require(
        set(observed) == expected_paths,
        f"manifest file-set drift: missing={sorted(expected_paths-set(observed))} extra={sorted(set(observed)-expected_paths)}",
    )
    mismatches = []
    for relative, expected in observed.items():
        actual = sha256(ROOT / relative)
        if actual != expected:
            mismatches.append((relative, expected, actual))
    require(not mismatches, f"manifest hash mismatches: {mismatches[:5]}")
    return {"file_count": len(observed), "sha256": sha256(manifest)}


def verify_orbit_atlas() -> dict[str, Any]:
    for name in ORBIT_ATLAS_SCIENTIFIC:
        require(sha256(ORBIT_ATLAS / "primary" / name) == sha256(ORBIT_ATLAS / "independent" / name), f"orbit-atlas implementation mismatch: {name}")
    coordinates = group_rows(load_json(ORBIT_ATLAS / "primary" / "coordinate_registry.json"))
    patterns = group_rows(load_json(ORBIT_ATLAS / "primary" / "pattern_registry.json"))
    collisions = group_rows(load_json(ORBIT_ATLAS / "primary" / "quadratic_collision_atlas.json"))
    witnesses = group_rows(load_json(ORBIT_ATLAS / "primary" / "cubic_witness_map.json"))
    expected = {
        "S4": {"order": 24, "degree": {"1": 1, "2": 5, "3": 13}, "patterns": 218, "pairs": 39, "fibres": 34},
        "A4": {"order": 12, "degree": {"1": 1, "2": 7, "3": 21}, "patterns": 368, "pairs": 51, "fibres": 51},
    }
    for group, target in expected.items():
        require(coordinates[group]["group_order"] == target["order"], f"{group} group order")
        require(coordinates[group]["degree_counts"] == target["degree"], f"{group} degree counts")
        require(len(coordinates[group]["rows"]) == sum(target["degree"].values()), f"{group} coordinate count")
        require(len(patterns[group]["rows"]) == target["patterns"], f"{group} pattern count")
        require(collisions[group]["colliding_pair_count"] == target["pairs"], f"{group} collision pairs")
        require(collisions[group]["collision_fibre_count"] == target["fibres"], f"{group} collision fibres")
        rows = witnesses[group]["rows"]
        require(len(rows) == target["pairs"], f"{group} witness coverage")
        require(len({row["pair_id"] for row in rows}) == target["pairs"], f"{group} duplicate witness pair")
        require(all(row["separating_coordinates"] for row in rows), f"{group} empty witness")
    return {group: {"coordinates": sum(row["degree"].values()), "patterns": row["patterns"], "residual_pairs": row["pairs"]} for group, row in expected.items()}


def verify_minimum_fingerprints() -> dict[str, Any]:
    primary = group_rows(load_json(MINIMUM / "primary" / "minimum_fingerprints.json"))
    independent = group_rows(load_json(MINIMUM / "independent" / "minimum_fingerprints.json"))
    lower = group_rows(load_json(MINIMUM / "primary" / "lower_bound_certificate.json"))
    expected = {"S4": (19, 23653, 26, 7, 11), "A4": (29, 67528, 58, 11, 22)}
    for group, (coordinates, pairs, reduced, minimum, nodes) in expected.items():
        for implementation in (primary, independent):
            require(implementation[group]["coordinate_count"] == coordinates, f"{group} coordinate count")
            require(implementation[group]["full_pair_count"] == pairs, f"{group} full pairs")
            require(implementation[group]["reduced_constraint_count"] == reduced, f"{group} reduced constraints")
            require(implementation[group]["minimum_size"] == minimum, f"{group} minimum")
            require(implementation[group]["all_full_pairs_separated"], f"{group} upper support")
        require(primary[group]["canonical_coordinate_ids"] == independent[group]["canonical_coordinate_ids"], f"{group} implementation optimum mismatch")
        require(lower[group]["certificate_type"] == "complete_branch_dag_v1", f"{group} certificate type")
        require(lower[group]["claimed_lower_bound"] == minimum, f"{group} lower bound")
        require(lower[group]["proof_node_count"] == nodes, f"{group} proof nodes")
    output = run(python_command(ROOT / "scripts" / "verify_minimum_fingerprints.py", "--root", str(MINIMUM), "--no-write"))
    require("MINIMUM_FINGERPRINTS_CERTIFICATE_PASS" in output, "MINIMUM checker token missing")
    return {group: {"minimum": values[3], "full_pairs": values[1], "proof_nodes": values[4]} for group, values in expected.items()}


def verify_family_degree_boundary() -> dict[str, Any]:
    a_path = FAMILY / "primary" / "family_probe.json"
    b_path = FAMILY / "independent" / "family_probe.json"
    require(sha256(a_path) == sha256(b_path), "family-degree implementations differ")
    family = group_rows(load_json(a_path))
    expected = {
        "S3": (16, {"1": 1, "2": 4, "3": 4}, 2),
        "A3": (24, {"1": 2, "2": 5, "3": 8}, 2),
        "S4": (218, {"1": 1, "2": 5, "3": 13}, 3),
        "A4": (368, {"1": 1, "2": 7, "3": 21}, 3),
        "S5": (9608, {"1": 1, "2": 5, "3": 16}, "GT3"),
        "A5": (17824, {"1": 1, "2": 6, "3": 21}, "GT3"),
    }
    for group, (patterns, coordinates, boundary) in expected.items():
        require(family[group]["pattern_orbit_count"] == patterns, f"{group} family patterns")
        require(family[group]["coordinate_counts"] == coordinates, f"{group} family coordinates")
        require(family[group]["reconstruction_degree_within_panel"] == boundary, f"{group} degree-three boundary")
    structural = group_rows(load_json(FAMILY / "structural" / "finite_theorem_certificate.json"))
    for group, graph, edges, packing, minimum in (("S4", "K5", 10, 2, 7), ("A4", "K7", 21, 4, 11)):
        row = structural[group]
        require(row["complete_quadratic_graph"]["graph"] == graph, f"{group} graph")
        require(row["complete_quadratic_graph"]["edge_count"] == edges, f"{group} graph edges")
        require(row["disjoint_cubic_constraints"]["packing_lower_bound"] == packing, f"{group} cubic packing")
        require(row["disjoint_cubic_constraints"]["pairwise_disjoint"], f"{group} cubic overlap")
        require(row["lower_bound_arithmetic"]["lower_bound"] == minimum, f"{group} structural minimum")
    output = run(python_command(ROOT / "scripts" / "verify_family_degree.py", "--root", str(FAMILY), "--no-write"))
    require("FAMILY_DEGREE_CERTIFICATE_PASS" in output, "FAMILY checker token missing")
    return {group: {"patterns": values[0], "degree_three_boundary": values[2]} for group, values in expected.items()}


def verify_five_vertex() -> dict[str, Any]:
    payload_path = N5_DATA / "canonical_payload.json"
    raw = payload_path.read_bytes()
    payload = json.loads(raw)
    require(canonical_json_bytes(payload) == raw, "five-vertex payload is not canonical JSON")
    require(payload.get("schema") == "orbit_sum_canonical_payload_v1", "five-vertex payload schema")
    require(
        sha256(payload_path) == sha256(N5_DATA / "independent" / "reconstructed_payload.json"),
        "independent five-vertex payload mismatch",
    )
    groups = payload["groups"]
    expected = {
        "S4": (218, [1, 5, 13], 39, 39, 0),
        "A4": (368, [1, 7, 21], 51, 51, 0),
        "S5": (9608, [1, 5, 16, 61], 190, 190, 0),
        "A5": (17824, [1, 6, 21, 96], 113, 105, 8),
    }
    for group, (patterns, profile, residual, tree_separated, tree_blind) in expected.items():
        row = groups[group]
        require(row["pattern_orbit_count"] == patterns, f"{group} pattern count")
        require(row["coordinate_profile_degrees_1_to_top"] == profile, f"{group} coordinate profile")
        require(row["residual_pair_count"] == residual, f"{group} residual pairs")
        require(row["pairs_with_a_tree_separator"] == tree_separated, f"{group} tree separators")
        require(row["tree_blind_pair_count"] == tree_blind, f"{group} tree-blind count")
    require(groups["A5"]["index_two_split_pair_count"] == 54, "A5 split-pair count")
    require(groups["A5"]["all_tree_blind_pairs_are_index_two_split_pairs"] is True, "A5 tree-blind classification")
    require(groups["S5"]["tree_only_cover"]["minimum"] == 5, "S5 tree-only minimum")
    require(groups["S5"]["tree_only_cover"]["solution_count"] == 88, "S5 tree-only solution count")
    conditional = {
        group: (
            groups[group]["conditional_top_degree_extension"]["minimum"],
            groups[group]["conditional_top_degree_extension"]["solution_count_before_external_quotient"],
        )
        for group in ("S4", "A4", "S5", "A5")
    }
    require(conditional == {"S4": (2, 2), "A4": (4, 128), "S5": (4, 2), "A5": (4, 200)}, "conditional extension rows")

    with tempfile.TemporaryDirectory(prefix="orbit_sum_core_") as raw_tmp:
        tmp = Path(raw_tmp)
        reconstruction_output = run(
            python_command(FIVE_VERTEX_SCRIPTS / "checker" / "reconstruct.py", "--project-root", str(ROOT), "--producer", str(N5_DATA), "--output", str(tmp / "reconstruction")),
            timeout=420,
        )
        require("PASS_FIVE_VERTEX_PAYLOAD_RECONSTRUCTION" in reconstruction_output, "independent payload reconstruction failed")
        lower_output = run(
            python_command(FIVE_VERTEX_SCRIPTS / "checker" / "verify_lower_bounds.py", "--project-root", str(ROOT), "--producer", str(N5_DATA), "--output", str(tmp / "lower"), "--check-only"),
            timeout=900,
        )
        require("PASS_FIVE_VERTEX_MINIMUM_CERTIFICATES" in lower_output, "five-vertex lower-DAG verification failed")
        require("S5_nodes=63589" in lower_output and "A5_nodes=213648" in lower_output, "five-vertex node census")
    return {
        "patterns": [218, 368, 9608, 17824],
        "profiles": [[1, 5, 13], [1, 7, 21], [1, 5, 16, 61], [1, 6, 21, 96]],
        "exact_degrees": [3, 3, 4, 4],
        "global_minima": [7, 11, 14, 17],
        "residual_pairs": [39, 51, 190, 113],
        "tree_separated_pairs": [39, 51, 190, 105],
        "tree_blind_pairs": [0, 0, 0, 8],
        "lower_dag_nodes": [63589, 213648],
        "conditional_minima": [2, 4, 4, 4],
        "conditional_solution_counts": [2, 128, 2, 200],
    }


def validate_theorem_summary_payload(value: dict[str, Any]) -> None:
    require(value == expected_theorem_summary(), "theorem summary schema/value drift")


def compact_surface(text: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"\\\s+", "", text))


def normalize_claim_text(text: str) -> str:
    # Preserve comparison signs and words while removing Markdown/TeX markup
    # that otherwise makes equivalent public claims look different.
    return re.sub(r"\s+", " ", re.sub(r"[`$\\{}_^~]", " ", text).lower()).strip()


def validate_scope_ceiling_texts(texts: dict[str, str]) -> None:
    positive_widening_patterns = (
        re.compile(
            r"\b(?:theorem|result|statement|reconstruction)\b.{0,160}"
            r"\b(?:holds?|applies|extends?|is valid|is true)\b.{0,100}"
            r"\b(?:all|every|arbitrary)\s+(?:n|vertex counts?)\b"
        ),
        re.compile(
            r"\b(?:holds?|applies|extends?|is valid|is true)\b.{0,80}"
            r"\b(?:n\s*>\s*5|n\s+above\s+five|vertex counts?\s+above\s+five)\b"
        ),
        re.compile(r"\bevery\s+n\s+above\s+five\b"),
        re.compile(r"\b(?:all|every|arbitrary)\s+n\s*>\s*5\b"),
        re.compile(
            r"\b(?:theorem|result|statement|reconstruction)\b.{0,160}"
            r"\b(?:all|every)\s+(?:orders?|sizes?|vertex counts?)\s+above\s+five\b"
        ),
    )
    false_status_patterns = (
        re.compile(r"\b(?:is|was|has been)\s+(?:externally\s+)?(?:published|peer reviewed|reproduced|verified)\b"),
        re.compile(r"\b(?:we|this (?:paper|work|repository))\s+(?:claim|claims|establish|establishes)\s+(?:novelty|priority|firstness)\b"),
    )
    violations: list[tuple[str, str]] = []
    for name, text in texts.items():
        normalized = normalize_claim_text(text)
        for pattern in (*positive_widening_patterns, *false_status_patterns):
            if pattern.search(normalized):
                violations.append((name, pattern.pattern))
    require(not violations, f"positive claim exceeds theorem-summary scope: {violations}")


def validate_public_four_tuples(texts: dict[str, str]) -> None:
    tuple_pattern = re.compile(
        r"(?<!\d)(\d{1,6})\s*,\s*(\d{1,6})\s*,\s*(\d{1,6})\s*,\s*(\d{1,6})(?!\d)"
    )
    conflicts: list[tuple[str, tuple[int, int, int, int]]] = []
    for name, text in texts.items():
        for match in tuple_pattern.finditer(text):
            row = tuple(int(item) for item in match.groups())
            if row not in ALLOWED_PUBLIC_FOUR_TUPLES:
                conflicts.append((name, row))
    require(not conflicts, f"undeclared public four-tuple: {conflicts}")


def validate_textual_summary_surfaces(value: dict[str, Any], surfaces: dict[str, str]) -> None:
    rows = value["cases"]
    degrees = ",".join(str(rows[group]["reconstruction_degree"]) for group in CASE_ORDER)
    dictionaries = ",".join(str(rows[group]["dictionary_size"]) for group in CASE_ORDER)
    minima = ",".join(str(rows[group]["global_minimum"]) for group in CASE_ORDER)
    requirements = {
        "README.md": tuple(
            f"|`{group}`|{rows[group]['reconstruction_degree']}|{rows[group]['dictionary_size']}|{rows[group]['global_minimum']}|"
            for group in CASE_ORDER
        ),
        "docs/CLAIM_LEDGER.md": (f"`{degrees}`", f"`{dictionaries}`", f"`{minima}`"),
        "docs/PUBLIC_CLAIM_BOUNDARY.md": (f"`{degrees}`", f"`{dictionaries}`", f"`{minima}`"),
        "paper/sections/01_introduction.tex": (
            rf"\rho(n,G)={degrees}.",
            f"${dictionaries}$coordinates",
            rf"\tau(n,G)={minima}.",
        ),
        "paper/tables/T01_exact_panel.tex": tuple(
            f"${group[0]}_{group[1]}$&{rows[group]['pattern_orbits']:,}"
            for group in CASE_ORDER
        ),
        "paper/sections/04_n4.tex": ("$7$of$19$for$S_4$and$11$of$29$for$A_4$",),
        "paper/sections/05_n5.tex": ("$14$of$83$and$17$of$124$",),
        "paper/sections/06_tree_index_two.tex": ("$39$$S_4$and$51$$A_4$", "$105$ofthe$113$"),
        "paper/sections/07_conditional.tex": ("(2,2),(4,128),(4,2),(4,200)",),
    }
    require(set(surfaces) == set(requirements), "theorem-summary textual surface set")
    for name, fragments in requirements.items():
        compact = compact_surface(surfaces[name])
        missing = [fragment for fragment in fragments if compact_surface(fragment) not in compact]
        require(not missing, f"theorem summary mismatch in {name}: {missing}")

    validate_scope_ceiling_texts(surfaces)


def validate_pdf_summary(value: dict[str, Any], page_texts: list[str]) -> None:
    require(len(page_texts) >= 14, "PDF too short for theorem-summary anchors")
    rows = value["cases"]
    tuples = (
        ",".join(str(rows[group]["reconstruction_degree"]) for group in CASE_ORDER),
        ",".join(str(rows[group]["dictionary_size"]) for group in CASE_ORDER),
        ",".join(str(rows[group]["global_minimum"]) for group in CASE_ORDER),
    )
    compact = compact_surface("\n".join(page_texts))
    require(all(token in compact for token in tuples), "PDF theorem tuple mismatch")
    require("7of19forS4and11of29forA4" in compact, "PDF n=4 theorem mismatch")
    require("14of83and17of124" in compact, "PDF n=5 theorem mismatch")
    require("105ofthe113" in compact, "PDF tree/index-two mismatch")
    require("(2,2),(4,128),(4,2),(4,200)" in compact, "PDF conditional tuple mismatch")


def verify_theorem_summary(
    four_vertex_atlas: dict[str, Any],
    four_vertex_minima: dict[str, Any],
    structural_boundary: dict[str, Any],
    five_vertex: dict[str, Any],
) -> dict[str, Any]:
    require(THEOREM_SUMMARY.is_file(), "missing certificates/theorem_summary.json")
    raw = THEOREM_SUMMARY.read_bytes()
    value = json.loads(raw)
    require(pretty_canonical_json_bytes(value) == raw, "theorem_summary.json is not canonical JSON")
    validate_theorem_summary_payload(value)
    rows = value["cases"]

    require(
        [rows[group]["reconstruction_degree"] for group in CASE_ORDER] == five_vertex["exact_degrees"],
        "theorem summary/checker degree mismatch",
    )
    require(
        [rows[group]["dictionary_size"] for group in CASE_ORDER]
        == [sum(profile) for profile in five_vertex["profiles"]],
        "theorem summary/checker dictionary mismatch",
    )
    for field in (
        "patterns",
        "global_minima",
        "residual_pairs",
        "tree_separated_pairs",
        "tree_blind_pairs",
        "conditional_minima",
        "conditional_solution_counts",
    ):
        summary_field = {
            "patterns": "pattern_orbits",
            "global_minima": "global_minimum",
            "residual_pairs": "residual_pairs_before_top_degree",
            "tree_separated_pairs": "tree_separated_pairs",
            "tree_blind_pairs": "tree_blind_pairs",
            "conditional_minima": "conditional_extension_minimum",
            "conditional_solution_counts": "conditional_extension_solution_count",
        }[field]
        require(
            [rows[group][summary_field] for group in CASE_ORDER] == five_vertex[field],
            f"theorem summary/checker {field} mismatch",
        )
    require(
        [rows["S5"]["lower_dag_nodes"], rows["A5"]["lower_dag_nodes"]] == five_vertex["lower_dag_nodes"],
        "theorem summary/checker n=5 DAG mismatch",
    )
    for group in ("S4", "A4"):
        require(four_vertex_atlas[group]["patterns"] == rows[group]["pattern_orbits"], f"{group} summary/orbit-atlas pattern mismatch")
        require(four_vertex_atlas[group]["residual_pairs"] == rows[group]["residual_pairs_before_top_degree"], f"{group} summary/orbit-atlas residual mismatch")
        require(four_vertex_minima[group]["minimum"] == rows[group]["global_minimum"], f"{group} summary/minimum mismatch")
        require(four_vertex_minima[group]["proof_nodes"] == rows[group]["lower_dag_nodes"], f"{group} summary/lower-DAG mismatch")
        require(structural_boundary[group]["degree_three_boundary"] == rows[group]["reconstruction_degree"], f"{group} summary/family-degree mismatch")
    for group in ("S5", "A5"):
        require(structural_boundary[group]["degree_three_boundary"] == "GT3", f"{group} FAMILY lower-degree collision boundary")

    surface_names = (
        "README.md",
        "docs/CLAIM_LEDGER.md",
        "docs/PUBLIC_CLAIM_BOUNDARY.md",
        "paper/sections/01_introduction.tex",
        "paper/tables/T01_exact_panel.tex",
        "paper/sections/04_n4.tex",
        "paper/sections/05_n5.tex",
        "paper/sections/06_tree_index_two.tex",
        "paper/sections/07_conditional.tex",
    )
    surfaces = {name: (ROOT / name).read_text(encoding="utf-8") for name in surface_names}
    validate_textual_summary_surfaces(value, surfaces)

    from pypdf import PdfReader

    page_texts = [page.extract_text() or "" for page in PdfReader(str(PDF)).pages]
    validate_pdf_summary(value, page_texts)
    return {
        "sha256": sha256(THEOREM_SUMMARY),
        "cases": list(CASE_ORDER),
        "cross_checked_surfaces": len(surfaces) + 4 + 1,
        "status": "PASS_CANONICAL_THEOREM_SUMMARY",
    }


def all_public_text_files() -> Iterable[Path]:
    suffixes = {".md", ".tex", ".sty", ".bib", ".py", ".json", ".csv", ".yaml", ".yml", ".cff", ".txt"}
    for path in build_manifest.package_files():
        if path.suffix.lower() in suffixes or path.name == "LICENSE":
            yield path


def distributed_pdf_paths(root: Path = ROOT) -> list[str]:
    rows: list[str] = []
    for path in root.rglob("*.pdf"):
        relative = path.relative_to(root)
        if ".git" in relative.parts or "tmp" in relative.parts:
            continue
        rows.append(relative.as_posix())
    return sorted(rows)


def verify_boundary_and_hygiene() -> dict[str, Any]:
    manuscript_files = [path for path in (ROOT / "paper").rglob("*") if path.is_file() and path.suffix.lower() in {".tex", ".sty", ".bib", ".md"}]
    manuscript_forbidden = (
        "P" + "58",
        "G" + "8U",
        "INTERNAL" + " DRAFT",
        "NOT FOR" + " CIRCULATION",
        "PRIVATE" + " UNIFIED",
    )
    for path in manuscript_files:
        text = path.read_text(encoding="utf-8", errors="strict").upper()
        for token in manuscript_forbidden:
            require(token not in text, f"internal governance token in manuscript: {token} in {path.relative_to(ROOT)}")

    # Build the probes without embedding the exact forbidden strings in this
    # verifier: the verifier is itself part of the text surface it audits.
    drive_prefix = r"(?<![A-Za-z0-9+.-])" + r"[A-Za-z]" + ":" + r"[\\/]"
    framework_fragment = r"(?:^|[\\/])" + "HA" + "N" + r"[\\/]" + "FRAME" + "WORK"
    codex_fragment = re.escape("." + "codex")
    file_uri_fragment = "file" + "://"
    absolute_patterns = (
        re.compile(drive_prefix),
        re.compile(framework_fragment, re.I),
        re.compile(codex_fragment, re.I),
        re.compile(file_uri_fragment, re.I),
    )
    secret_patterns = (
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
        re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
        re.compile(r"sk-[A-Za-z0-9]{24,}"),
    )
    text_count = 0
    for path in all_public_text_files():
        text_count += 1
        text = path.read_text(encoding="utf-8", errors="strict")
        require(not any(pattern.search(text) for pattern in absolute_patterns), f"private absolute path in {path.relative_to(ROOT)}")
        require(not any(pattern.search(text) for pattern in secret_patterns), f"credential-like token in {path.relative_to(ROOT)}")

    forbidden_extensions = {".eprint", ".doc", ".docx", ".rtf", ".epub"}
    require(not [path for path in ROOT.rglob("*") if path.is_file() and path.suffix.lower() in forbidden_extensions], "third-party full-text-like files present")
    pdfs = distributed_pdf_paths()
    require(pdfs == [PDF.relative_to(ROOT).as_posix()], f"unexpected PDF set: {pdfs}")
    require(not [path for path in ROOT.rglob("*") if path.is_symlink()], "filesystem symlink present")

    boundary = (ROOT / "docs" / "PUBLIC_CLAIM_BOUNDARY.md").read_text(encoding="utf-8")
    for required in ("7,11,14,17", "arbitrary invariants", "n>5", "physical chirality", "novelty", "public-release status"):
        require(required.lower() in boundary.lower(), f"claim boundary missing {required!r}")
    cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    require(f'version: "{PACKAGE_VERSION}"' in cff and "date-released:" not in cff, "CFF version status")
    return {"text_files_scanned": text_count, "distributed_pdfs": pdfs, "symlinks": 0}


def resolve_pdf(value: Any) -> Any:
    return value.get_object() if hasattr(value, "get_object") else value


def font_descriptors(font: Any) -> list[Any]:
    font = resolve_pdf(font)
    descendants = resolve_pdf(font.get("/DescendantFonts")) if font.get("/DescendantFonts") is not None else None
    fonts = [resolve_pdf(item) for item in descendants] if descendants else [font]
    return [resolve_pdf(item.get("/FontDescriptor")) for item in fonts if item.get("/FontDescriptor") is not None]


def verify_pdf() -> dict[str, Any]:
    require(PDF.is_file(), f"missing paper PDF: {PDF}")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required; install requirements.txt") from exc
    reader = PdfReader(str(PDF))
    require(not reader.is_encrypted, "PDF is encrypted")
    metadata = reader.metadata or {}
    author = str(metadata.get("/Author", ""))
    title = str(metadata.get("/Title", ""))
    subject = str(metadata.get("/Subject", ""))
    require(author == "Oleksiy Babanskyy", f"PDF author metadata: {author!r}")
    require(title.startswith("Exact Squarefree Orbit-Sum Reconstruction of Four- and Five-Vertex"), f"PDF title metadata: {title!r}")
    require("draft" not in subject.lower() and "private" not in subject.lower(), f"PDF subject carries draft/private status: {subject!r}")
    require(18 <= len(reader.pages) <= 30, f"unexpected PDF page count: {len(reader.pages)}")

    texts: list[str] = []
    sizes: list[tuple[float, float]] = []
    unsafe: list[str] = []
    font_count = 0
    unembedded: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        texts.append(text)
        require(len(text) >= 80, f"page {number} appears blank or nearly blank")
        sizes.append((round(float(page.mediabox.width), 3), round(float(page.mediabox.height), 3)))
        resources = resolve_pdf(page.get("/Resources")) if page.get("/Resources") is not None else {}
        fonts = resolve_pdf(resources.get("/Font")) if resources and resources.get("/Font") is not None else {}
        for name, font in (fonts or {}).items():
            font_count += 1
            descriptors = font_descriptors(font)
            if not descriptors or not all(any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")) for descriptor in descriptors):
                unembedded.append(f"page {number}:{name}")
        for reference in page.get("/Annots", []):
            annotation = resolve_pdf(reference)
            action = resolve_pdf(annotation.get("/A")) if annotation.get("/A") is not None else None
            if not action:
                continue
            kind = str(action.get("/S", ""))
            uri = str(action.get("/URI", ""))
            if kind == "/URI" and re.match(r"^https?://", uri, re.I):
                continue
            if kind != "/GoTo":
                unsafe.append(f"page {number}:{kind}:{uri}")
    require(len(set(sizes)) == 1, f"inconsistent page sizes: {sorted(set(sizes))}")
    require(font_count > 0 and not unembedded, f"unembedded or unresolvable PDF fonts: {unembedded[:10]}")

    all_text = "\n".join(texts)
    compact = re.sub(r"\s+", "", all_text)
    required = (
        "Unified four- and five-vertex reconstruction theorem",
        "Four-vertex global minimum fingerprints",
        "Five-vertex degree and global minimum fingerprints",
        "PASS_ORBIT_SUM_PACKAGE_CORE",
        "References",
    )
    require(not [token for token in required if token not in all_text and token not in compact], "required PDF text missing")
    private_drive_fragment = "G:" + "\\" + "Repositories"
    private_framework_fragment = "HA" + "N" + "/" + "FRAME" + "WORK"
    for forbidden in (
        "INTERNAL" + " DRAFT",
        "NOT FOR" + " CIRCULATION",
        "P" + "58-",
        "G" + "8U",
        private_drive_fragment,
        private_framework_fragment,
    ):
        require(forbidden.lower() not in all_text.lower(), f"forbidden PDF text: {forbidden}")

    catalog = resolve_pdf(reader.trailer["/Root"])
    require(str(catalog.get("/Lang", "")) == "en-US", f"PDF language metadata: {catalog.get('/Lang')!r}")
    dangerous = [key for key in ("/AA", "/JavaScript", "/EmbeddedFiles") if key in catalog]
    open_action = resolve_pdf(catalog.get("/OpenAction")) if catalog.get("/OpenAction") is not None else None
    if open_action is not None and (not isinstance(open_action, dict) or str(open_action.get("/S", "")) != "/GoTo"):
        dangerous.append("/OpenAction")
    attachments = getattr(reader, "attachments", {}) or {}
    require(not dangerous and not attachments and not unsafe, f"unsafe PDF surface: {dangerous}, {list(attachments)}, {unsafe}")
    return {
        "bytes": PDF.stat().st_size,
        "pages": len(reader.pages),
        "sha256": sha256(PDF),
        "page_size_points": list(sizes[0]),
        "font_resource_occurrences": font_count,
        "all_fonts_embedded": True,
        "unsafe_actions": 0,
        "attachments": 0,
    }


def expected_attestation(manifest: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "orbit_sum_build_attestation_v1",
        "artifact_kind": "versioned_release_build",
        "version": PACKAGE_VERSION,
        "intended_release_tag": RELEASE_TAG,
        "author": {"name": "Oleksiy Babanskyy", "orcid": "0009-0001-6176-6208"},
        "repository": "https://github.com/aconsciousfractal/FCIG-Exact-Squarefree-Orbit-Sum-Reconstruction",
        "manifest": {
            "path": "MANIFEST_SHA256.txt",
            "file_count": manifest["file_count"],
            "sha256": manifest["sha256"],
        },
        "paper": {
            "path": "paper/Exact_Squarefree_Orbit_Sum_Reconstruction_of_Four_and_Five_Vertex_Loopless_Digraphs.pdf",
            "bytes": paper["bytes"],
            "pages": paper["pages"],
            "sha256": paper["sha256"],
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


def validate_attestation_payload(value: dict[str, Any], manifest: dict[str, Any], paper: dict[str, Any]) -> None:
    require(value == expected_attestation(manifest, paper), "attestation schema/value drift")


def verify_attestation(manifest: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
    require(ATTESTATION.is_file(), "missing BUILD_ATTESTATION.json")
    raw = ATTESTATION.read_bytes()
    value = parse_strict_json_object(raw, str(ATTESTATION))
    require(raw == pretty_canonical_json_bytes(value), "attestation is not pretty-canonical JSON")
    validate_attestation_payload(value, manifest, paper)
    return {"sha256": sha256(ATTESTATION), "artifact_kind": value["artifact_kind"], "version": value["version"]}


def sanitized_git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        environment.pop(name, None)
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def git(command: list[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["git", "--no-replace-objects", *command],
        # Git for Windows honors core.longpaths on a normal absolute path but
        # can resolve HEAD without later resolving its object when cwd itself
        # carries the Win32 extended-length prefix. Python filesystem calls
        # retain the prefix; Git receives the equivalent ordinary spelling.
        cwd=regular_windows_path(ROOT),
        env=sanitized_git_environment(),
        text=True,
        encoding="utf-8",
        errors="replace",
        input=input_text,
        capture_output=True,
        check=False,
        timeout=120,
    )
    require(result.returncode == 0, f"git command failed: {' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def git_blob_oid(payload: bytes, object_format: str) -> str:
    require(object_format in {"sha1", "sha256"}, f"unsupported Git object format: {object_format}")
    state = hashlib.new(object_format)
    state.update(f"blob {len(payload)}\0".encode("ascii"))
    state.update(payload)
    return state.hexdigest()


def verify_reachable_history_boundary(git_state: str) -> dict[str, Any]:
    require(git_state in {"development", "candidate", "release"}, f"unknown Git state: {git_state}")
    head = git(["rev-parse", "HEAD"]).strip()
    branch = git(["branch", "--show-current"]).strip()
    if git_state in {"candidate", "release"}:
        require(not branch or branch == "main", f"{git_state} branch must be main or detached, observed {branch!r}")

    refs: list[tuple[str, str]] = []
    for row in git(["for-each-ref", "--format=%(refname)%09%(objectname)"]).splitlines():
        refname, object_name = row.split("\t", 1)
        refs.append((refname, object_name))
    tag_refs = [name for name, _ in refs if name.startswith("refs/tags/")]
    unexpected_refs = [
        name
        for name, _ in refs
        if not (name.startswith("refs/heads/") or name.startswith("refs/remotes/") or name.startswith("refs/tags/"))
    ]
    require(not unexpected_refs, f"unexpected Git ref namespaces: {unexpected_refs}")
    release_ref = f"refs/tags/{RELEASE_TAG}"
    release_tag_present = release_ref in tag_refs
    release_tag_target: str | None = None
    release_tag_kind: str | None = None
    if release_tag_present:
        release_tag_target = git(["rev-parse", f"{release_ref}^{{commit}}"]).strip()
        release_tag_kind = git(["cat-file", "-t", release_ref]).strip()
    if git_state == "candidate":
        require(not release_tag_present, f"candidate checkout already contains {release_ref}")
    elif git_state == "release":
        require(release_tag_present, f"release checkout is missing {release_ref}")
        require(release_tag_target == head, f"{release_ref} does not point to HEAD")
        require(release_tag_kind == "tag", f"{release_ref} must be an annotated tag")

    commit_rows = [row.split() for row in git(["rev-list", "--parents", "HEAD"]).splitlines() if row]
    require(commit_rows, "HEAD has no reachable commit history")
    root_commits = [row[0] for row in commit_rows if len(row) == 1]
    require(len(root_commits) == 1, f"HEAD ancestry must have exactly one root, observed {len(root_commits)}")

    project_token = ("p" + "58").lower()
    gate_token = ("g" + "8u").lower()
    forbidden_history_paths: list[str] = []
    for commit_row in commit_rows:
        commit = commit_row[0]
        tree_paths = [path for path in git(["ls-tree", "-r", "--name-only", "-z", commit]).split("\0") if path]
        for path in tree_paths:
            lowered = path.lower()
            if (
                lowered.startswith(("outputs/", "experiments/", "g" + "8u1/"))
                or project_token in lowered
                or gate_token in lowered
                or "agent_handoff" in lowered
            ):
                forbidden_history_paths.append(f"{commit}:{path}")
    require(not forbidden_history_paths, f"historical governance paths are reachable: {forbidden_history_paths[:5]}")
    return {
        "git_state": git_state,
        "branch": branch or "DETACHED",
        "reachable_commits": len(commit_rows),
        "reachable_refs": len(refs),
        "root_commit": root_commits[0],
        "tags": len(tag_refs),
        "release_tag": RELEASE_TAG,
        "release_tag_present": release_tag_present,
        "release_tag_target": release_tag_target,
        "release_tag_kind": release_tag_kind,
        "historical_governance_paths": 0,
    }


def verify_git_boundary(skip: bool, git_state: str = "development") -> dict[str, Any]:
    if skip:
        return {"status": "SKIPPED_DEVELOPMENT_ONLY", "git_state": git_state}
    require((ROOT / ".git").exists(), "exact Git boundary requires a repository checkout")
    top = Path(git(["rev-parse", "--show-toplevel"]).strip()).resolve()
    require(comparable_path(top) == comparable_path(ROOT), f"unexpected Git root: {top}")
    require(not git(["replace", "-l"]).strip(), "Git replacement refs are present")
    git_dir = Path(git(["rev-parse", "--absolute-git-dir"]).strip())
    require(not (git_dir / "info" / "grafts").exists(), "Git graft file is present")
    require(not (git_dir / "objects" / "info" / "alternates").exists(), "alternate object database is present")
    history = verify_reachable_history_boundary(git_state)
    status = git(["status", "--porcelain=v1", "--untracked-files=all"])
    require(not (ROOT / ".gitmodules").exists(), "submodules are not allowed")

    stage = git(["ls-files", "--stage", "-z"])
    entries = [entry for entry in stage.split("\0") if entry]
    index_entries: dict[str, tuple[str, str]] = {}
    for entry in entries:
        metadata, path = entry.split("\t", 1)
        mode, oid, stage_number = metadata.split()
        require(stage_number == "0", f"unmerged index stage {stage_number}: {path}")
        require(mode in {"100644", "100755"}, f"non-regular tracked mode {mode}: {path}")
        require(path not in index_entries, f"duplicate index path: {path}")
        index_entries[path] = (mode, oid)
    tracked = sorted(index_entries)
    require(not status.strip(), f"worktree is not clean:\n{status}")

    tree_entries: dict[str, tuple[str, str]] = {}
    for entry in [item for item in git(["ls-tree", "-r", "-z", "HEAD"]).split("\0") if item]:
        metadata, path = entry.split("\t", 1)
        mode, object_type, oid = metadata.split()
        require(object_type == "blob", f"non-blob HEAD entry {object_type}: {path}")
        tree_entries[path] = (mode, oid)
    require(index_entries == tree_entries, "HEAD/index file, mode, or object mismatch")

    flag_rows: dict[str, str] = {}
    for entry in [item for item in git(["ls-files", "-v", "-z"]).split("\0") if item]:
        require(len(entry) >= 3 and entry[1] == " ", f"malformed git index-flag row: {entry!r}")
        flag_rows[entry[2:]] = entry[0]
    require(set(flag_rows) == set(tracked), "Git index-flag path-set mismatch")
    nonstandard_flags = [(path, flag_rows[path]) for path in tracked if flag_rows[path] != "H"]
    require(not nonstandard_flags, f"nonstandard Git index flags: {nonstandard_flags[:5]}")

    expected_tracked = {build_manifest.relative_name(path) for path in build_manifest.package_files()}
    expected_tracked.update(name for name in ALLOWED_UNMANIFESTED_TRACKED if (ROOT / name).is_file())
    require(
        set(tracked) == expected_tracked,
        f"tracked file-set escapes manifest boundary: missing={sorted(expected_tracked-set(tracked))[:5]} "
        f"extra={sorted(set(tracked)-expected_tracked)[:5]}",
    )

    # NUL framing is required here. In subprocess text mode on Windows, LF
    # input is translated to CRLF; git check-attr --stdin would then treat the
    # carriage return as part of every pathname and falsely report every
    # filter as unspecified.
    attr_input = "\0".join(tracked) + "\0"
    attributes = git(["check-attr", "--stdin", "-z", "filter"], input_text=attr_input)
    fields = attributes.split("\0")
    require(fields[-1] == "" and (len(fields) - 1) % 3 == 0, "malformed NUL-framed git check-attr output")
    filter_rows = [tuple(fields[index : index + 3]) for index in range(0, len(fields) - 1, 3)]
    active_filters = [(path, value) for path, attribute, value in filter_rows if attribute != "filter" or value != "unspecified"]
    require(not active_filters, f"tracked file has a Git filter: {active_filters[:5]}")
    lfs_pointers = []
    for relative in tracked:
        path = ROOT / Path(relative)
        if path.is_file() and path.stat().st_size <= 1024:
            prefix = path.read_bytes()[:200]
            if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
                lfs_pointers.append(relative)
    require(not lfs_pointers, f"Git LFS pointers present: {lfs_pointers}")

    object_format = git(["rev-parse", "--show-object-format"]).strip()
    worktree_mismatches: list[str] = []
    for relative in tracked:
        path = ROOT / Path(relative)
        if not path.is_file() or git_blob_oid(path.read_bytes(), object_format) != index_entries[relative][1]:
            worktree_mismatches.append(relative)
    require(not worktree_mismatches, f"HEAD/index/worktree byte mismatch: {worktree_mismatches[:5]}")
    return {
        "status": "PASS",
        "commit": git(["rev-parse", "HEAD"]).strip(),
        "tree": git(["rev-parse", "HEAD^{tree}"]).strip(),
        "tracked_files": len(tracked),
        "manifest_boundary_files": len(expected_tracked),
        "nonstandard_index_flags": 0,
        "worktree_blob_mismatches": 0,
        "replace_refs": 0,
        "lfs_pointers": 0,
        "symlink_modes": 0,
        "reachable_commits": history["reachable_commits"],
        "reachable_refs": history["reachable_refs"],
        "history_root_commit": history["root_commit"],
        "history_tags": history["tags"],
        "git_state": history["git_state"],
        "release_tag": history["release_tag"],
        "release_tag_present": history["release_tag_present"],
        "release_tag_target": history["release_tag_target"],
        "release_tag_kind": history["release_tag_kind"],
        "historical_governance_paths": history["historical_governance_paths"],
    }


def compare_scientific(generated: Path, published: Path, names: Iterable[str]) -> None:
    for name in names:
        require(sha256(generated / name) == sha256(published / name), f"regenerated artifact mismatch: {published.name}/{name}")


def full_replay() -> dict[str, Any]:
    # Keep replay products under the ignored tmp/ directory for portable
    # same-volume paths on Windows. TemporaryDirectory removes the full tree.
    temporary_root = ROOT / "tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="orbit_sum_full_", dir=temporary_root) as raw:
        tmp = Path(raw)
        orbit_primary, orbit_independent = tmp / "orbit_primary", tmp / "orbit_independent"
        run(python_command(ROOT / "scripts" / "build_orbit_atlas_primary.py", "--output", str(orbit_primary)))
        run(python_command(ROOT / "scripts" / "build_orbit_atlas_independent.py", "--output", str(orbit_independent)))
        compare_scientific(orbit_primary, ORBIT_ATLAS / "primary", ORBIT_ATLAS_SCIENTIFIC)
        compare_scientific(orbit_independent, ORBIT_ATLAS / "independent", ORBIT_ATLAS_SCIENTIFIC)

        minima_primary, minima_independent = tmp / "minima_primary", tmp / "minima_independent"
        run(python_command(ROOT / "scripts" / "solve_minimum_fingerprints_primary.py", "--output", str(minima_primary)))
        run(python_command(ROOT / "scripts" / "solve_minimum_fingerprints_independent.py", "--output", str(minima_independent)))
        compare_scientific(minima_primary, MINIMUM / "primary", ("instance.json", "lower_bound_certificate.json", "minimum_fingerprints.json"))
        compare_scientific(minima_independent, MINIMUM / "independent", ("minimum_fingerprints.json",))

        family_primary = tmp / "family_primary"
        family_independent = tmp / "family_independent"
        family_structural = tmp / "family_structural"
        run(python_command(ROOT / "scripts" / "build_family_degree_primary.py", "--output", str(family_primary)))
        run(python_command(ROOT / "scripts" / "build_family_degree_independent.py", "--output", str(family_independent)))
        run(python_command(ROOT / "scripts" / "build_structural_certificate.py", "--output", str(family_structural)))
        compare_scientific(family_primary, FAMILY / "primary", ("family_probe.json",))
        compare_scientific(family_independent, FAMILY / "independent", ("family_probe.json",))
        compare_scientific(family_structural, FAMILY / "structural", ("finite_theorem_certificate.json",))

        producer, checker = tmp / "n5_producer", tmp / "n5_checker"
        run(python_command(FIVE_VERTEX_SCRIPTS / "producer" / "main.py", "--project-root", str(ROOT), "--output", str(producer)), timeout=420)
        compare_scientific(producer, N5_DATA, ("canonical_payload.json",))
        output = run(python_command(FIVE_VERTEX_SCRIPTS / "checker" / "reconstruct.py", "--project-root", str(ROOT), "--producer", str(producer), "--output", str(checker)), timeout=420)
        require("PASS_FIVE_VERTEX_PAYLOAD_RECONSTRUCTION" in output, "full payload comparison")
        compare_scientific(checker, N5_DATA / "independent", ("reconstructed_payload.json",))

    build = run(
        python_command(ROOT / "scripts" / "build_paper.py", "--check-byte-identical"),
        timeout=600,
    )
    require("PASS_PAPER_BYTE_IDENTITY" in build, "isolated source/PDF byte identity")
    tests = run(python_command(Path("-m"), "unittest", "discover", "-s", "tests", "-v"), timeout=900)
    require("OK" in tests or tests == "", "regression test endpoint missing")
    return {
        "independent_scientific_outputs_matched": 30,
        "isolated_source_pdf_byte_identity": "PASS",
        "tests": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("core", "full"), default="core")
    parser.add_argument(
        "--git-state",
        choices=("development", "candidate", "release"),
        default="development",
        help="select maintainable checkout, untagged final candidate, or tagged release boundary",
    )
    parser.add_argument("--skip-git-boundary", action="store_true", help="allow verification before the prepared package is committed")
    parser.add_argument("--write-summary", action="store_true")
    args = parser.parse_args()

    manifest = verify_manifest()
    four_vertex_atlas = verify_orbit_atlas()
    four_vertex_minima = verify_minimum_fingerprints()
    structural_boundary = verify_family_degree_boundary()
    unified_five_vertex = verify_five_vertex()
    result: dict[str, Any] = {
        "schema_version": "orbit_sum_package_verification_v1",
        "profile": args.profile,
        "git_state": args.git_state,
        "optimized_python": not __debug__,
        "manifest": manifest,
        "four_vertex_atlas": four_vertex_atlas,
        "four_vertex_minima": four_vertex_minima,
        "structural_boundary": structural_boundary,
        "unified_five_vertex": unified_five_vertex,
        "boundary_and_hygiene": verify_boundary_and_hygiene(),
    }
    paper = verify_pdf()
    result["paper"] = paper
    result["theorem_summary"] = verify_theorem_summary(
        four_vertex_atlas,
        four_vertex_minima,
        structural_boundary,
        unified_five_vertex,
    )
    result["attestation"] = verify_attestation(manifest, paper)
    result["git_boundary"] = verify_git_boundary(args.skip_git_boundary, args.git_state)
    if not args.skip_git_boundary:
        result["identity_binding"] = {
            "commit": result["git_boundary"]["commit"],
            "tree": result["git_boundary"]["tree"],
            "attestation_sha256": result["attestation"]["sha256"],
        }
    if args.profile == "full":
        result["full_replay"] = full_replay()
    result["status"] = f"PASS_ORBIT_SUM_PACKAGE_{args.profile.upper()}"
    if args.write_summary:
        output = ROOT / "tmp" / "package_verification.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(result["status"])
    print(json.dumps({"profile": args.profile, "git_state": args.git_state, "optimized_python": not __debug__, "paper": paper, "git_boundary": result["git_boundary"], "status": result["status"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ORBIT_SUM_VERIFY_FAIL|{type(exc).__name__}|{exc}", file=sys.stderr)
        raise
