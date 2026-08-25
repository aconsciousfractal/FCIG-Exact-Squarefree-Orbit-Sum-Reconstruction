#!/usr/bin/env python3
"""Build the finite four-vertex structural lower-bound certificate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTANCE_PATH = (
    ROOT
    / "certificates"
    / "minimum_fingerprints"
    / "primary"
    / "instance.json"
)
MINIMUM_PATH = (
    ROOT
    / "certificates"
    / "minimum_fingerprints"
    / "primary"
    / "minimum_fingerprints.json"
)
INPUTS = (
    ROOT / "docs" / "NORMALIZATION_LOCK.md",
    ROOT / "schemas" / "family_degree_contract_v1.json",
    ROOT / "schemas" / "family_degree_specification.yaml",
    INSTANCE_PATH,
    MINIMUM_PATH,
)
DECLARED = {
    "S4": {"q": 5, "indices": (11, 16), "minimum": 7},
    "A4": {"q": 7, "indices": (22, 23, 24, 29), "minimum": 11},
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


def read_json(path: Path) -> dict[str, object]:
    with open(native(path), "r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_new_json(path: Path, value: object) -> None:
    if os.path.exists(native(path)):
        raise FileExistsError(f"refusing to overwrite governed artifact: {path}")
    os.makedirs(native(path.parent), exist_ok=True)
    with open(native(path), "wb") as stream:
        stream.write(canonical_bytes(value))


def verify_inputs() -> dict[str, str]:
    missing = [str(path) for path in INPUTS if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing scientific inputs: {missing}")
    return {path.relative_to(ROOT).as_posix(): sha256(path) for path in INPUTS}


def constraint_row(row: dict[str, object], index: int) -> dict[str, object]:
    return {
        "constraint_id": row["constraint_id"],
        "constraint_index": index,
        "coordinate_ids": row["coordinate_ids"],
        "left_pattern_id": row["left_pattern_id"],
        "mask_int": row["mask_int"],
        "right_pattern_id": row["right_pattern_id"],
        "witness_pair_id": row["witness_pair_id"],
    }


def build_group_certificate(
    group_row: dict[str, object], minimum_row: dict[str, object]
) -> dict[str, object]:
    group = str(group_row["group"])
    declared = DECLARED[group]
    coordinate_ids = [str(value) for value in group_row["coordinate_ids"]]
    constraints = list(group_row["inclusion_minimal_constraints"])
    distinct_masks = list(group_row["distinct_separator_masks"])
    degree_one = [value for value in coordinate_ids if "-D1-" in value]
    degree_two = [value for value in coordinate_ids if "-D2-" in value]
    degree_three = [value for value in coordinate_ids if "-D3-" in value]
    if degree_one != [f"{group}-D1-C000"]:
        raise ValueError(f"{group} degree-one registry mismatch")
    if len(degree_two) != int(declared["q"]):
        raise ValueError(f"{group} quadratic coordinate count mismatch")

    singleton_rows = [
        (index, row)
        for index, row in enumerate(constraints)
        if list(row["coordinate_ids"]) == degree_one
    ]
    if len(singleton_rows) != 1:
        raise ValueError(f"{group} forced singleton constraint not unique")
    singleton_index, singleton = singleton_rows[0]

    expected_edges = {tuple(edge) for edge in combinations(degree_two, 2)}
    actual_edges: dict[tuple[str, str], tuple[int, dict[str, object]]] = {}
    for index, row in enumerate(constraints):
        coordinates = tuple(str(value) for value in row["coordinate_ids"])
        if len(coordinates) == 2 and set(coordinates).issubset(degree_two):
            actual_edges[tuple(sorted(coordinates))] = (index, row)
    if set(actual_edges) != expected_edges:
        raise ValueError(f"{group} quadratic constraints are not exactly K{len(degree_two)}")
    quadratic_edges = [
        {
            **constraint_row(actual_edges[edge][1], actual_edges[edge][0]),
            "edge": list(edge),
        }
        for edge in sorted(expected_edges)
    ]

    cubic_blocks: list[dict[str, object]] = []
    cubic_sets: list[set[str]] = []
    for index in declared["indices"]:
        row = constraints[int(index)]
        coordinates = [str(value) for value in row["coordinate_ids"]]
        if not coordinates or not set(coordinates).issubset(degree_three):
            raise ValueError(f"{group} declared cubic block {index} is not cubic-only")
        cubic_blocks.append(constraint_row(row, int(index)))
        cubic_sets.append(set(coordinates))
    for left, right in combinations(cubic_sets, 2):
        if left & right:
            raise ValueError(f"{group} declared cubic blocks overlap")

    support = [str(value) for value in minimum_row["canonical_coordinate_ids"]]
    support_mask = 0
    for coordinate in support:
        support_mask |= 1 << coordinate_ids.index(coordinate)
    missed = [
        int(row["separator_mask_index"])
        for row in distinct_masks
        if support_mask & int(row["mask_int"]) == 0
    ]
    if missed:
        raise ValueError(f"{group} canonical feasible support misses {len(missed)} masks")

    forced = 1
    vertex_cover = len(degree_two) - 1
    cubic_packing = len(cubic_blocks)
    lower_bound = forced + vertex_cover + cubic_packing
    minimum = int(minimum_row["minimum_size"])
    if minimum != int(declared["minimum"]) or lower_bound != minimum:
        raise ValueError(f"{group} structural lower bound does not close the optimum")

    all_block_coordinates = [set(degree_one), set(degree_two), set(degree_three)]
    if any(a & b for a, b in combinations(all_block_coordinates, 2)):
        raise ValueError(f"{group} degree blocks are not disjoint")

    return {
        "canonical_feasible_support": {
            "all_distinct_separator_masks_hit": True,
            "coordinate_ids": support,
            "distinct_separator_mask_count": len(distinct_masks),
            "full_pair_count": int(group_row["full_pair_count"]),
            "support_size": len(support),
        },
        "complete_quadratic_graph": {
            "edge_count": len(quadratic_edges),
            "edges": quadratic_edges,
            "graph": f"K{len(degree_two)}",
            "quadratic_coordinate_ids": degree_two,
            "vertex_cover_lower_bound": vertex_cover,
            "vertex_cover_proof": (
                "The complement of a vertex cover is independent; a complete graph "
                "has independence number one."
            ),
        },
        "disjoint_cubic_constraints": {
            "blocks": cubic_blocks,
            "cubic_coordinate_count": len(degree_three),
            "packing_lower_bound": cubic_packing,
            "pairwise_disjoint": True,
        },
        "forced_degree_one": constraint_row(singleton, singleton_index),
        "group": group,
        "lower_bound_arithmetic": {
            "block_coordinate_sets_disjoint": True,
            "claimed_minimum": minimum,
            "cubic_packing": cubic_packing,
            "forced_degree_one": forced,
            "lower_bound": lower_bound,
            "quadratic_vertex_cover": vertex_cover,
            "sum_expression": f"1+{vertex_cover}+{cubic_packing}={lower_bound}",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "certificates" / "family_degree" / "structural",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    input_hashes = verify_inputs()
    instance = read_json(INSTANCE_PATH)
    minimum = read_json(MINIMUM_PATH)
    instance_rows = {str(row["group"]): row for row in instance["groups"]}
    minimum_rows = {str(row["group"]): row for row in minimum["groups"]}
    groups = [
        build_group_certificate(instance_rows[group], minimum_rows[group])
        for group in ("S4", "A4")
    ]
    certificate = {
        "claim_ceiling": "finite_four_vertex_dictionary_only",
        "experiment_id": "FAMILY_DEGREE",
        "finite_scope": {
            "coordinate_universe": "all_squarefree_coordinates_through_degree_three",
            "groups": ["S4", "A4"],
            "pattern_pairs": {"S4": 23653, "A4": 67528},
        },
        "groups": groups,
        "schema_version": "family_degree_finite_theorem_certificate_v1",
        "theorem": (
            "For each declared four-vertex action, every separating fingerprint "
            "has size at least 1+(q-1)+r, and the canonical support attains equality."
        ),
    }
    certificate_path = args.output / "finite_theorem_certificate.json"
    write_new_json(certificate_path, certificate)
    build_summary = {
        "artifact_hashes": {
            "finite_theorem_certificate.json": sha256(certificate_path),
        },
        "experiment_id": "FAMILY_DEGREE",
        "implementation": "explicit_minimum_constraint_block_extractor",
        "independence_declaration": {
            "consumed_family_enumerations": False,
            "scope": "distributed_minimum_instance_only",
        },
        "input_hashes": input_hashes,
        "random_seed": None,
        "implementation_id": "STRUCTURAL_CERTIFICATE",
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "schema_version": "family_degree_build_summary_v1",
        "summary": {row["group"]: row["lower_bound_arithmetic"]["lower_bound"] for row in groups},
        "verdict": "PASS",
    }
    write_new_json(args.output / "build_summary.json", build_summary)
    print("STRUCTURAL_CERTIFICATE_PASS|S4=7|A4=11|blocks=D1+K5_K7+cubic_packing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
