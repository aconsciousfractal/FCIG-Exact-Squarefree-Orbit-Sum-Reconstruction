#!/usr/bin/env python3
"""Independently rebuild and verify the four-vertex minimum certificates."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
EXPERIMENT = "MINIMUM_FINGERPRINTS"
GROUP_ORDER = ("S4", "A4")
EXPECTED = {
    "S4": {"coordinates": 19, "patterns": 218, "pairs": 23653},
    "A4": {"coordinates": 29, "patterns": 368, "pairs": 67528},
}
SPECIFICATION = PROJECT / "schemas" / "minimum_fingerprints_specification.yaml"
CONTRACT = PROJECT / "schemas" / "minimum_fingerprints_contract_v1.json"
COORDINATE_CSV = (
    PROJECT
    / "certificates"
    / "orbit_atlas"
    / "independent"
    / "normalized_coordinate_registry.csv"
)
PATTERN_CSV = (
    PROJECT
    / "certificates"
    / "orbit_atlas"
    / "independent"
    / "normalized_pattern_registry.csv"
)
INPUTS = (SPECIFICATION, CONTRACT, COORDINATE_CSV, PATTERN_CSV)
STDLIB_IMPORTS = {
    "argparse",
    "csv",
    "hashlib",
    "json",
    "os",
    "pathlib",
    "sys",
    "time",
    "typing",
}


def native(path: Path) -> str:
    value = str(path.resolve())
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        return "\\\\?\\" + value
    return value


def sha256(path: Path) -> str:
    state = hashlib.sha256()
    with open(native(path), "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            state.update(block)
    return state.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with open(native(path), "r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise TypeError(f"JSON root is not an object: {path}")
    return value


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(native(path), "w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def path_exists(path: Path) -> bool:
    return os.path.exists(native(path))


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(native(path), "r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def bits(mask: int) -> list[int]:
    result: list[int] = []
    while mask:
        bit = mask & -mask
        result.append(bit.bit_length() - 1)
        mask ^= bit
    return result


def pair_line(pair_id: str, left: str, right: str, mask: int) -> bytes:
    return (
        json.dumps([pair_id, left, right, mask], separators=(",", ":")) + "\n"
    ).encode("ascii")


def state_hash(uncovered: tuple[int, ...]) -> str:
    return hashlib.sha256(
        ",".join(str(index) for index in uncovered).encode("ascii")
    ).hexdigest()


def minimal_masks(values: set[int]) -> list[int]:
    ordered = sorted(values, key=lambda mask: (mask.bit_count(), mask))
    answer: list[int] = []
    for mask in ordered:
        if not any(candidate & mask == candidate for candidate in answer):
            answer.append(mask)
    return answer


def verify_inputs() -> dict[str, str]:
    missing = [str(path) for path in INPUTS if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing scientific inputs: {missing}")
    return {path.relative_to(PROJECT).as_posix(): sha256(path) for path in INPUTS}


def source_audit(path: Path) -> dict[str, object]:
    with open(native(path), "r", encoding="utf-8") as stream:
        source = stream.read()
    tree = ast.parse(source, filename=str(path))
    imports: set[str] = set()
    relative_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_import = True
            if node.module:
                imports.add(node.module.split(".")[0])
    nonstandard = sorted(imports - STDLIB_IMPORTS - {"__future__"})
    if relative_import or nonstandard:
        raise ValueError(
            f"implementation source independence failure: {path.name}: "
            f"relative={relative_import}, nonstandard={nonstandard}"
        )
    return {
        "imports": sorted(imports),
        "relative_import": relative_import,
        "sha256": sha256(path),
        "standard_library_only": True,
    }


def rebuild_instances() -> dict[str, dict[str, Any]]:
    coordinate_rows = read_csv(COORDINATE_CSV)
    pattern_rows = read_csv(PATTERN_CSV)
    rebuilt: dict[str, dict[str, Any]] = {}
    for group in GROUP_ORDER:
        coordinates = [row for row in coordinate_rows if row["group"] == group]
        patterns = [row for row in pattern_rows if row["group"] == group]
        coordinate_ids = [row["coordinate_id"] for row in coordinates]
        pattern_ids = [row["pattern_id"] for row in patterns]
        signatures = [json.loads(row["signature_through_3"]) for row in patterns]
        expected = EXPECTED[group]
        if len(coordinate_ids) != expected["coordinates"]:
            raise ValueError(f"{group} coordinate count mismatch")
        if len(pattern_ids) != expected["patterns"]:
            raise ValueError(f"{group} pattern count mismatch")
        if pattern_ids != sorted(pattern_ids):
            raise ValueError(f"{group} pattern order mismatch")
        if any(len(row) != len(coordinate_ids) for row in signatures):
            raise ValueError(f"{group} signature width mismatch")

        pair_hasher = hashlib.sha256()
        pair_rows: list[dict[str, Any]] = []
        pair_by_id: dict[str, dict[str, Any]] = {}
        mask_records: dict[int, dict[str, Any]] = {}
        pair_index = 0
        for left_index, left_id in enumerate(pattern_ids):
            for right_index in range(left_index + 1, len(pattern_ids)):
                right_id = pattern_ids[right_index]
                mask = 0
                for coordinate, (left, right) in enumerate(
                    zip(signatures[left_index], signatures[right_index], strict=True)
                ):
                    if left != right:
                        mask |= 1 << coordinate
                if mask == 0:
                    raise ValueError(f"{group} empty full-pair separator")
                pair_id = f"{group}-PAIR-{pair_index:05d}"
                pair_hasher.update(pair_line(pair_id, left_id, right_id, mask))
                pair_row = {
                    "left_pattern_id": left_id,
                    "mask_int": mask,
                    "pair_id": pair_id,
                    "right_pattern_id": right_id,
                }
                pair_rows.append(pair_row)
                pair_by_id[pair_id] = pair_row
                record = mask_records.get(mask)
                if record is None:
                    mask_records[mask] = {
                        "duplicate_pair_count": 1,
                        "left_pattern_id": left_id,
                        "right_pattern_id": right_id,
                        "witness_pair_id": pair_id,
                    }
                else:
                    record["duplicate_pair_count"] += 1
                pair_index += 1
        if pair_index != expected["pairs"]:
            raise ValueError(f"{group} pair count mismatch")
        distinct = sorted(mask_records, key=lambda mask: (mask.bit_count(), mask))
        reduced = minimal_masks(set(distinct))
        rebuilt[group] = {
            "coordinate_ids": coordinate_ids,
            "distinct_masks": distinct,
            "full_pair_sha256": pair_hasher.hexdigest(),
            "mask_records": mask_records,
            "pair_by_id": pair_by_id,
            "pair_rows": pair_rows,
            "pattern_ids": pattern_ids,
            "reduced_masks": reduced,
        }
    return rebuilt


def validate_instance_group(
    group: str, observed: dict[str, Any], rebuilt: dict[str, Any]
) -> None:
    coordinate_ids = rebuilt["coordinate_ids"]
    distinct = rebuilt["distinct_masks"]
    reduced = rebuilt["reduced_masks"]
    records = rebuilt["mask_records"]
    if observed.get("group") != group:
        raise ValueError(f"{group} instance group label mismatch")
    scalar_checks = {
        "coordinate_count": len(coordinate_ids),
        "coordinate_ids": coordinate_ids,
        "distinct_separator_mask_count": len(distinct),
        "full_pair_count": len(rebuilt["pair_rows"]),
        "full_pair_sha256": rebuilt["full_pair_sha256"],
        "inclusion_minimal_constraint_count": len(reduced),
        "pattern_count": len(rebuilt["pattern_ids"]),
    }
    for key, expected in scalar_checks.items():
        if observed.get(key) != expected:
            raise ValueError(f"{group} instance mismatch on {key}")

    observed_distinct = observed.get("distinct_separator_masks")
    if not isinstance(observed_distinct, list) or len(observed_distinct) != len(distinct):
        raise ValueError(f"{group} distinct separator rows mismatch")
    for index, (row, mask) in enumerate(zip(observed_distinct, distinct, strict=True)):
        record = records[mask]
        expected = {
            "coordinate_ids": [coordinate_ids[i] for i in bits(mask)],
            "duplicate_pair_count": record["duplicate_pair_count"],
            "left_pattern_id": record["left_pattern_id"],
            "mask_int": mask,
            "mask_popcount": mask.bit_count(),
            "right_pattern_id": record["right_pattern_id"],
            "separator_mask_index": index,
            "witness_pair_id": record["witness_pair_id"],
        }
        for key, value in expected.items():
            if row.get(key) != value:
                raise ValueError(f"{group} distinct row {index} mismatch on {key}")

    observed_reduced = observed.get("inclusion_minimal_constraints")
    if not isinstance(observed_reduced, list) or len(observed_reduced) != len(reduced):
        raise ValueError(f"{group} reduced constraint rows mismatch")
    for index, (row, mask) in enumerate(zip(observed_reduced, reduced, strict=True)):
        record = records[mask]
        expected = {
            "constraint_id": f"{group}-CON-{index:05d}",
            "coordinate_ids": [coordinate_ids[i] for i in bits(mask)],
            "duplicate_pair_count": record["duplicate_pair_count"],
            "left_pattern_id": record["left_pattern_id"],
            "mask_int": mask,
            "mask_popcount": mask.bit_count(),
            "right_pattern_id": record["right_pattern_id"],
            "witness_pair_id": record["witness_pair_id"],
        }
        for key, value in expected.items():
            if row.get(key) != value:
                raise ValueError(f"{group} reduced row {index} mismatch on {key}")


def validate_instance(instance: dict[str, Any], rebuilt: dict[str, dict[str, Any]]) -> None:
    if instance.get("schema_version") != "minimum_fingerprints_instance_v1":
        raise ValueError("instance schema mismatch")
    groups = instance.get("groups")
    if not isinstance(groups, list) or [row.get("group") for row in groups] != list(GROUP_ORDER):
        raise ValueError("instance group order mismatch")
    for row in groups:
        group = str(row["group"])
        validate_instance_group(group, row, rebuilt[group])


def selected_mask(ids: list[str], coordinate_ids: list[str]) -> int:
    if len(ids) != len(set(ids)) or ids != sorted(ids, key=coordinate_ids.index):
        raise ValueError("selected coordinate IDs are duplicate or noncanonical")
    mask = 0
    for coordinate_id in ids:
        try:
            index = coordinate_ids.index(coordinate_id)
        except ValueError as error:
            raise ValueError(f"unknown selected coordinate: {coordinate_id}") from error
        mask |= 1 << index
    return mask


def validate_solution(
    solution: dict[str, Any], rebuilt: dict[str, dict[str, Any]], label: str
) -> dict[str, dict[str, Any]]:
    if solution.get("schema_version") != "minimum_fingerprints_minimum_fingerprints_v1":
        raise ValueError(f"{label} solution schema mismatch")
    rows = solution.get("groups")
    if not isinstance(rows, list) or [row.get("group") for row in rows] != list(GROUP_ORDER):
        raise ValueError(f"{label} solution group order mismatch")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = str(row["group"])
        data = rebuilt[group]
        ids = list(row.get("canonical_coordinate_ids", []))
        mask = selected_mask(ids, data["coordinate_ids"])
        minimum = int(row.get("minimum_size", -1))
        if len(ids) != minimum or mask.bit_count() != minimum:
            raise ValueError(f"{label} {group} witness cardinality mismatch")
        if row.get("canonical_coordinate_mask_int") != mask:
            raise ValueError(f"{label} {group} witness mask mismatch")
        if row.get("full_pair_count") != len(data["pair_rows"]):
            raise ValueError(f"{label} {group} pair count mismatch")
        if row.get("full_pair_sha256") != data["full_pair_sha256"]:
            raise ValueError(f"{label} {group} pair hash mismatch")
        if row.get("coordinate_count") != len(data["coordinate_ids"]):
            raise ValueError(f"{label} {group} coordinate count mismatch")
        if row.get("distinct_separator_mask_count") not in (
            None,
            len(data["distinct_masks"]),
        ):
            raise ValueError(f"{label} {group} distinct mask count mismatch")
        if row.get("reduced_constraint_count") != len(data["reduced_masks"]):
            raise ValueError(f"{label} {group} reduced constraint count mismatch")
        missed = [pair for pair in data["pair_rows"] if pair["mask_int"] & mask == 0]
        if missed or row.get("all_full_pairs_separated") is not True:
            raise ValueError(f"{label} {group} witness misses {len(missed)} pairs")
        result[group] = {"ids": ids, "mask": mask, "minimum": minimum}
    return result


def require_agreement(
    primary: dict[str, dict[str, Any]], independent: dict[str, dict[str, Any]]
) -> None:
    for group in GROUP_ORDER:
        if primary[group] != independent[group]:
            raise ValueError(f"{group} implementation optimum or canonical witness disagreement")


def verify_packing_certificate(
    group: str,
    certificate: dict[str, Any],
    rebuilt: dict[str, Any],
    expected_lower_bound: int,
) -> dict[str, int]:
    witnesses = certificate.get("witnesses")
    if not isinstance(witnesses, list) or len(witnesses) != expected_lower_bound:
        raise ValueError(f"{group} packing size mismatch")
    reduced = rebuilt["reduced_masks"]
    used = 0
    seen: set[int] = set()
    for witness in witnesses:
        index = int(witness.get("constraint_index", -1))
        if index < 0 or index >= len(reduced) or index in seen:
            raise ValueError(f"{group} invalid packing constraint index")
        seen.add(index)
        mask = reduced[index]
        if witness.get("mask_int") != mask:
            raise ValueError(f"{group} packing mask mismatch")
        pair_id = str(witness.get("witness_pair_id"))
        pair = rebuilt["pair_by_id"].get(pair_id)
        if pair is None or pair["mask_int"] != mask:
            raise ValueError(f"{group} packing pair recomputation mismatch")
        if pair["left_pattern_id"] != witness.get("left_pattern_id"):
            raise ValueError(f"{group} packing left pair ID mismatch")
        if pair["right_pattern_id"] != witness.get("right_pattern_id"):
            raise ValueError(f"{group} packing right pair ID mismatch")
        if used & mask:
            raise ValueError(f"{group} packing masks overlap")
        used |= mask
    if certificate.get("packing_size") != len(witnesses):
        raise ValueError(f"{group} declared packing size mismatch")
    return {"packing_size": len(witnesses), "proof_nodes": 0}


def verify_dag_certificate(
    group: str,
    certificate: dict[str, Any],
    rebuilt: dict[str, Any],
    expected_lower_bound: int,
) -> dict[str, int]:
    reduced: list[int] = rebuilt["reduced_masks"]
    nodes_value = certificate.get("nodes")
    if not isinstance(nodes_value, list):
        raise ValueError(f"{group} proof nodes missing")
    nodes: dict[str, dict[str, Any]] = {}
    for node in nodes_value:
        identifier = str(node.get("node_id"))
        if identifier in nodes:
            raise ValueError(f"{group} duplicate proof node")
        nodes[identifier] = node
    if certificate.get("proof_node_count") != len(nodes):
        raise ValueError(f"{group} proof node count mismatch")
    root_state = tuple(range(len(reduced)))
    root_budget = expected_lower_bound - 1
    if certificate.get("root_budget") != root_budget:
        raise ValueError(f"{group} proof root budget mismatch")
    if certificate.get("root_uncovered_count") != len(root_state):
        raise ValueError(f"{group} proof root count mismatch")
    if certificate.get("root_uncovered_sha256") != state_hash(root_state):
        raise ValueError(f"{group} proof root state mismatch")
    root_id = str(certificate.get("root_node_id"))
    verified: dict[str, tuple[tuple[int, ...], int]] = {}
    visiting: set[str] = set()

    def visit(identifier: str, uncovered: tuple[int, ...], budget: int) -> None:
        previous = verified.get(identifier)
        if previous is not None:
            if previous != (uncovered, budget):
                raise ValueError(f"{group} DAG node reused with another state")
            return
        if identifier in visiting:
            raise ValueError(f"{group} proof DAG cycle")
        node = nodes.get(identifier)
        if node is None:
            raise ValueError(f"{group} missing referenced proof node")
        if node.get("budget") != budget:
            raise ValueError(f"{group} proof node budget mismatch")
        if node.get("uncovered_count") != len(uncovered):
            raise ValueError(f"{group} proof node uncovered count mismatch")
        if node.get("uncovered_sha256") != state_hash(uncovered):
            raise ValueError(f"{group} proof node state hash mismatch")
        if not uncovered:
            raise ValueError(f"{group} proof contains a feasible leaf")
        visiting.add(identifier)
        kind = node.get("kind")
        if kind == "budget_zero":
            if budget != 0:
                raise ValueError(f"{group} zero-budget leaf has nonzero budget")
        elif kind == "packing_leaf":
            indices = node.get("packing_constraint_indices")
            if not isinstance(indices, list) or len(indices) != budget + 1:
                raise ValueError(f"{group} packing leaf cardinality mismatch")
            if len(indices) != len(set(indices)):
                raise ValueError(f"{group} packing leaf repeats a constraint")
            used = 0
            for index in indices:
                if index not in uncovered:
                    raise ValueError(f"{group} packing leaf uses covered constraint")
                mask = reduced[index]
                if used & mask:
                    raise ValueError(f"{group} packing leaf masks overlap")
                used |= mask
        elif kind == "branch":
            if budget <= 0:
                raise ValueError(f"{group} branch has exhausted budget")
            branch_index = int(node.get("branch_constraint_index", -1))
            if branch_index not in uncovered:
                raise ValueError(f"{group} branch constraint is not uncovered")
            expected_coordinates = bits(reduced[branch_index])
            children = node.get("children")
            if not isinstance(children, list):
                raise ValueError(f"{group} branch children missing")
            observed_coordinates = [child.get("coordinate_index") for child in children]
            if observed_coordinates != expected_coordinates:
                raise ValueError(f"{group} branch child set is incomplete")
            for child in children:
                coordinate = int(child["coordinate_index"])
                bit = 1 << coordinate
                child_state = tuple(
                    index for index in uncovered if reduced[index] & bit == 0
                )
                visit(str(child["node_id"]), child_state, budget - 1)
        else:
            raise ValueError(f"{group} unknown proof node kind: {kind}")
        visiting.remove(identifier)
        verified[identifier] = (uncovered, budget)

    visit(root_id, root_state, root_budget)
    if set(verified) != set(nodes):
        raise ValueError(f"{group} proof contains unreachable nodes")
    return {"packing_size": 0, "proof_nodes": len(nodes)}


def verify_group_certificate(
    group: str,
    certificate: dict[str, Any],
    rebuilt: dict[str, Any],
    expected_lower_bound: int,
) -> dict[str, int | str]:
    if certificate.get("group") != group:
        raise ValueError(f"{group} certificate group mismatch")
    if certificate.get("claimed_lower_bound") != expected_lower_bound:
        raise ValueError(f"{group} lower-bound value mismatch")
    certificate_type = certificate.get("certificate_type")
    if certificate_type == "pairwise_disjoint_separator_packing_v1":
        stats = verify_packing_certificate(
            group, certificate, rebuilt, expected_lower_bound
        )
    elif certificate_type == "complete_branch_dag_v1":
        stats = verify_dag_certificate(group, certificate, rebuilt, expected_lower_bound)
    else:
        raise ValueError(f"{group} unsupported certificate type: {certificate_type}")
    return {"certificate_type": str(certificate_type), **stats}


def compare(root: Path, write_summary: bool = True) -> dict[str, Any]:
    started = time.perf_counter()
    input_hashes = verify_inputs()
    primary_root = root / "primary"
    independent_root = root / "independent"
    comparison_path = root / "verification_summary.json"
    if write_summary and path_exists(comparison_path):
        raise FileExistsError(f"refusing existing verification summary: {comparison_path}")

    instance_path = primary_root / "instance.json"
    certificate_path = primary_root / "lower_bound_certificate.json"
    solution_a_path = primary_root / "minimum_fingerprints.json"
    solution_b_path = independent_root / "minimum_fingerprints.json"
    instance = load_json(instance_path)
    certificates = load_json(certificate_path)
    solution_a = load_json(solution_a_path)
    solution_b = load_json(solution_b_path)

    rebuilt = rebuild_instances()
    validate_instance(instance, rebuilt)
    verified_a = validate_solution(solution_a, rebuilt, "primary")
    verified_b = validate_solution(solution_b, rebuilt, "independent")
    certificate_rows = certificates.get("groups")
    if not isinstance(certificate_rows, list):
        raise ValueError("certificate groups missing")
    certificate_by_group = {str(row["group"]): row for row in certificate_rows}
    summary: dict[str, Any] = {}
    require_agreement(verified_a, verified_b)
    for group in GROUP_ORDER:
        certificate_stats = verify_group_certificate(
            group,
            certificate_by_group[group],
            rebuilt[group],
            int(verified_a[group]["minimum"]),
        )
        summary[group] = {
            "canonical_coordinate_ids": verified_a[group]["ids"],
            "certificate_type": certificate_stats["certificate_type"],
            "distinct_separator_masks": len(rebuilt[group]["distinct_masks"]),
            "full_pair_count": len(rebuilt[group]["pair_rows"]),
            "full_pair_sha256": rebuilt[group]["full_pair_sha256"],
            "lower_bound": verified_a[group]["minimum"],
            "minimum_size": verified_a[group]["minimum"],
            "packing_size": certificate_stats["packing_size"],
            "proof_nodes": certificate_stats["proof_nodes"],
            "reduced_constraint_count": len(rebuilt[group]["reduced_masks"]),
            "implementation_agreement": True,
        }

    source_audits = {
        "PRIMARY_EXACT_SEARCH": source_audit(PROJECT / "scripts" / "solve_minimum_fingerprints_primary.py"),
        "INDEPENDENT_EXACT_SEARCH": source_audit(PROJECT / "scripts" / "solve_minimum_fingerprints_independent.py"),
    }
    verification_summary = {
        "canonical_witness_agreement": True,
        "certificate_checks": summary,
        "greedy_upper_bound_comparison": {
            "A4": {"certified_minimum": summary["A4"]["minimum_size"], "old_upper_bound": 12},
            "S4": {"certified_minimum": summary["S4"]["minimum_size"], "old_upper_bound": 8},
            "status": "STRICTLY_IMPROVED_NOT_RELABELLED",
        },
        "experiment_id": EXPERIMENT,
        "input_hashes": input_hashes,
        "full_pair_rebuild": {
            group: {
                "coordinate_count": len(rebuilt[group]["coordinate_ids"]),
                "distinct_separator_masks": len(rebuilt[group]["distinct_masks"]),
                "full_pair_count": len(rebuilt[group]["pair_rows"]),
                "full_pair_sha256": rebuilt[group]["full_pair_sha256"],
                "pattern_count": len(rebuilt[group]["pattern_ids"]),
                "reduced_constraint_count": len(rebuilt[group]["reduced_masks"]),
            }
            for group in GROUP_ORDER
        },
        "independent_lower_bound_certificate_pass": True,
        "implementation_optimum_agreement": True,
        "implementation_source_audits": source_audits,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "schema_version": "minimum_fingerprints_verification_summary_v1",
        "summary": summary,
        "verdict": "PASS",
    }
    if write_summary:
        save_json(comparison_path, verification_summary)
    return verification_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    root = args.root if args.root.is_absolute() else PROJECT / args.root
    try:
        summary = compare(root, write_summary=not args.no_write)
    except Exception as error:
        print(f"MINIMUM_FINGERPRINTS_CERTIFICATE_FAIL|{type(error).__name__}|{error}")
        return 1
    print(
        "MINIMUM_FINGERPRINTS_CERTIFICATE_PASS|"
        + "|".join(
            f"{group}=min{summary['summary'][group]['minimum_size']}"
            f"/lb{summary['summary'][group]['lower_bound']}"
            f"/nodes{summary['summary'][group]['proof_nodes']}"
            for group in GROUP_ORDER
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
