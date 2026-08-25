#!/usr/bin/env python3
"""Primary four-vertex orbit-atlas generator.

The implementation uses generator closure and lexicographic orbit minima.
Its scientific code is separate from the independent DSU implementation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import time


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "ORBIT_ATLAS"
IMPLEMENTATION_ID = "PRIMARY_ENUMERATION"
INPUTS = {
    "normalization": ROOT / "docs" / "NORMALIZATION_LOCK.md",
    "machine_contract": ROOT / "schemas" / "orbit_atlas_contract_v1.json",
    "specification": ROOT / "schemas" / "orbit_atlas_specification.yaml",
}
GROUP_ORDER = ("S4", "A4")
VERTICES = tuple(range(4))
ARCS = tuple((i, j) for i in VERTICES for j in VERTICES if i != j)
ARC_INDEX = {arc: index for index, arc in enumerate(ARCS)}
IDENTITY = (0, 1, 2, 3)
SCIENTIFIC_FILES = (
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


def native_path(path: Path) -> str:
    resolved = str(path.resolve())
    if os.name == "nt" and not resolved.startswith("\\\\?\\"):
        return "\\\\?\\" + resolved
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(native_path(path), "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    missing = [str(path) for path in INPUTS.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing specification inputs: {missing}")
    return {name: sha256(path) for name, path in INPUTS.items()}


def compose(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[int, ...]:
    """Return left after right, matching the public normalization."""
    return tuple(left[right[index]] for index in VERTICES)


def generated_group(generators: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
    known = {IDENTITY}
    frontier = [IDENTITY]
    while frontier:
        element = frontier.pop()
        for generator in generators:
            product = compose(element, generator)
            if product not in known:
                known.add(product)
                frontier.append(product)
    return tuple(sorted(known))


def build_groups() -> dict[str, tuple[tuple[int, ...], ...]]:
    transposition_01 = (1, 0, 2, 3)
    cycle_0123 = (1, 2, 3, 0)
    cycle_012 = (1, 2, 0, 3)
    cycle_013 = (1, 3, 2, 0)
    groups = {
        "S4": generated_group((transposition_01, cycle_0123)),
        "A4": generated_group((cycle_012, cycle_013)),
    }
    if len(groups["S4"]) != 24 or len(groups["A4"]) != 12:
        raise RuntimeError("generator closure did not produce S4/A4")
    return groups


def arc_action(permutation: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(ARC_INDEX[(permutation[i], permutation[j])] for i, j in ARCS)


def move_mask(mask: int, action: tuple[int, ...]) -> int:
    moved = 0
    for source, target in enumerate(action):
        if mask & (1 << source):
            moved |= 1 << target
    return moved


def mask_indices(mask: int) -> list[int]:
    return [index for index in range(len(ARCS)) if mask & (1 << index)]


def mask_arcs(mask: int) -> list[list[int]]:
    return [list(ARCS[index]) for index in mask_indices(mask)]


def subset_mask(indices: tuple[int, ...]) -> int:
    value = 0
    for index in indices:
        value |= 1 << index
    return value


def canonical_orbit(mask: int, actions: tuple[tuple[int, ...], ...]) -> tuple[int, tuple[int, ...]]:
    orbit = tuple(sorted({move_mask(mask, action) for action in actions}))
    return orbit[0], orbit


def coordinate_rows(
    group: str,
    permutations: tuple[tuple[int, ...], ...],
    actions: tuple[tuple[int, ...], ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for degree in (1, 2, 3):
        orbits: dict[int, tuple[int, ...]] = {}
        for support in itertools.combinations(range(len(ARCS)), degree):
            mask = subset_mask(support)
            canonical, orbit = canonical_orbit(mask, actions)
            previous = orbits.setdefault(canonical, orbit)
            if previous != orbit:
                raise RuntimeError("inconsistent coordinate orbit")
        for degree_index, canonical in enumerate(sorted(orbits)):
            orbit = orbits[canonical]
            stabilizer = sum(move_mask(canonical, action) == canonical for action in actions)
            if len(orbit) * stabilizer != len(permutations):
                raise RuntimeError("coordinate orbit-stabilizer failure")
            rows.append(
                {
                    "group": group,
                    "coordinate_id": f"{group}-D{degree}-C{degree_index:03d}",
                    "degree": degree,
                    "degree_index": degree_index,
                    "canonical_support_mask": canonical,
                    "canonical_support_hex": f"0x{canonical:03x}",
                    "support_arc_indices": mask_indices(canonical),
                    "support_arcs": mask_arcs(canonical),
                    "support_orbit_masks": list(orbit),
                    "orbit_size": len(orbit),
                    "setwise_stabilizer_order": stabilizer,
                }
            )
    return rows


def orbit_sum(pattern_mask: int, support_orbit: list[int]) -> int:
    return sum((support & pattern_mask) == support for support in support_orbit)


def pattern_rows(
    group: str,
    permutations: tuple[tuple[int, ...], ...],
    actions: tuple[tuple[int, ...], ...],
    coordinates: list[dict[str, object]],
) -> list[dict[str, object]]:
    pattern_orbits: dict[int, tuple[int, ...]] = {}
    for mask in range(1 << len(ARCS)):
        canonical, orbit = canonical_orbit(mask, actions)
        previous = pattern_orbits.setdefault(canonical, orbit)
        if previous != orbit:
            raise RuntimeError("inconsistent pattern orbit")

    through_1 = [row for row in coordinates if int(row["degree"]) <= 1]
    through_2 = [row for row in coordinates if int(row["degree"]) <= 2]
    through_3 = coordinates
    rows: list[dict[str, object]] = []
    for pattern_index, canonical in enumerate(sorted(pattern_orbits)):
        orbit = pattern_orbits[canonical]
        stabilizer = sum(move_mask(canonical, action) == canonical for action in actions)
        if len(orbit) * stabilizer != len(permutations):
            raise RuntimeError("pattern orbit-stabilizer failure")

        def signature(items: list[dict[str, object]]) -> list[int]:
            return [orbit_sum(canonical, list(item["support_orbit_masks"])) for item in items]

        rows.append(
            {
                "group": group,
                "pattern_id": f"{group}-P{pattern_index:03d}",
                "representative_mask": canonical,
                "canonical_mask": canonical,
                "canonical_hex": f"0x{canonical:03x}",
                "selected_arc_indices": mask_indices(canonical),
                "selected_arcs": mask_arcs(canonical),
                "orbit_masks": list(orbit),
                "orbit_size": len(orbit),
                "setwise_stabilizer_order": stabilizer,
                "signature_through_1": signature(through_1),
                "signature_through_2": signature(through_2),
                "signature_through_3": signature(through_3),
            }
        )
    covered = sorted(mask for row in rows for mask in list(row["orbit_masks"]))
    if covered != list(range(1 << len(ARCS))):
        raise RuntimeError("pattern registry is not a partition")
    return rows


def collision_rows(group: str, patterns: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    fibres: dict[tuple[int, ...], list[dict[str, object]]] = {}
    for row in patterns:
        key = tuple(int(value) for value in list(row["signature_through_2"]))
        fibres.setdefault(key, []).append(row)
    collisions = [
        (signature, sorted(rows, key=lambda item: int(item["canonical_mask"])))
        for signature, rows in fibres.items()
        if len(rows) > 1
    ]
    collisions.sort(key=lambda item: (item[0], [int(row["canonical_mask"]) for row in item[1]]))
    output: list[dict[str, object]] = []
    for index, (signature, rows) in enumerate(collisions):
        output.append(
            {
                "group": group,
                "fibre_id": f"{group}-QF{index:03d}",
                "signature_through_2": list(signature),
                "pattern_ids": [str(row["pattern_id"]) for row in rows],
                "canonical_masks": [int(row["canonical_mask"]) for row in rows],
                "fibre_size": len(rows),
            }
        )
    stats = {
        "group": group,
        "collision_fibre_count": len(output),
        "colliding_class_count": sum(int(row["fibre_size"]) for row in output),
        "colliding_pair_count": sum(math.comb(int(row["fibre_size"]), 2) for row in output),
        "max_fibre_size": max((int(row["fibre_size"]) for row in output), default=1),
        "rows": output,
    }
    return output, stats


def witness_rows(
    group: str,
    collisions: list[dict[str, object]],
    patterns: list[dict[str, object]],
    coordinates: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    pattern_by_id = {str(row["pattern_id"]): row for row in patterns}
    cubic_rows = [row for row in coordinates if int(row["degree"]) == 3]
    cubic_offset = len(coordinates) - len(cubic_rows)
    pending: list[dict[str, object]] = []
    for fibre in collisions:
        members = [pattern_by_id[pattern_id] for pattern_id in list(fibre["pattern_ids"])]
        for left, right in itertools.combinations(members, 2):
            left_signature = list(left["signature_through_3"])
            right_signature = list(right["signature_through_3"])
            separators: list[dict[str, object]] = []
            for local_index, coordinate in enumerate(cubic_rows):
                left_value = int(left_signature[cubic_offset + local_index])
                right_value = int(right_signature[cubic_offset + local_index])
                if left_value != right_value:
                    separators.append(
                        {
                            "coordinate_id": str(coordinate["coordinate_id"]),
                            "left_value": left_value,
                            "right_value": right_value,
                        }
                    )
            if not separators:
                raise RuntimeError("degree-three signature failed to separate a quadratic collision")
            pending.append(
                {
                    "group": group,
                    "fibre_id": str(fibre["fibre_id"]),
                    "left_pattern_id": str(left["pattern_id"]),
                    "right_pattern_id": str(right["pattern_id"]),
                    "left_mask": int(left["canonical_mask"]),
                    "right_mask": int(right["canonical_mask"]),
                    "separating_coordinates": separators,
                    "selected_coordinate_id": str(separators[0]["coordinate_id"]),
                }
            )
    pending.sort(key=lambda row: (int(row["left_mask"]), int(row["right_mask"])))
    for index, row in enumerate(pending):
        row["pair_id"] = f"{group}-QP{index:03d}"
    ordered = [
        {
            "group": row["group"],
            "pair_id": row["pair_id"],
            "fibre_id": row["fibre_id"],
            "left_pattern_id": row["left_pattern_id"],
            "right_pattern_id": row["right_pattern_id"],
            "left_mask": row["left_mask"],
            "right_mask": row["right_mask"],
            "separating_coordinates": row["separating_coordinates"],
            "selected_coordinate_id": row["selected_coordinate_id"],
        }
        for row in pending
    ]
    return ordered, {"group": group, "colliding_pair_count": len(ordered), "rows": ordered}


def minimum_extension(
    group: str,
    witnesses: list[dict[str, object]],
    coordinates: list[dict[str, object]],
) -> dict[str, object]:
    cubic_ids = [str(row["coordinate_id"]) for row in coordinates if int(row["degree"]) == 3]
    pair_ids = [str(row["pair_id"]) for row in witnesses]
    coverage: dict[str, set[str]] = {coordinate_id: set() for coordinate_id in cubic_ids}
    for row in witnesses:
        for separator in list(row["separating_coordinates"]):
            coverage[str(separator["coordinate_id"])].add(str(row["pair_id"]))
    target = set(pair_ids)
    lower_bound: list[dict[str, int]] = []
    minimum_sets: list[list[str]] = []
    for size in range(len(cubic_ids) + 1):
        tested = 0
        separating = 0
        current_sets: list[list[str]] = []
        for choice in itertools.combinations(cubic_ids, size):
            tested += 1
            covered: set[str] = set()
            for coordinate_id in choice:
                covered.update(coverage[coordinate_id])
            if covered == target:
                separating += 1
                current_sets.append(list(choice))
        lower_bound.append({"size": size, "tested_subset_count": tested, "separating_subset_count": separating})
        if current_sets:
            minimum_sets = current_sets
            break
    if not minimum_sets:
        raise RuntimeError("no cubic extension separates all pairs")
    if lower_bound[-1]["tested_subset_count"] != math.comb(len(cubic_ids), len(minimum_sets[0])):
        raise RuntimeError("subset enumeration count mismatch")
    return {
        "group": group,
        "cubic_coordinate_ids": cubic_ids,
        "collision_pair_ids": pair_ids,
        "coverage_by_coordinate": {
            coordinate_id: sorted(coverage[coordinate_id]) for coordinate_id in cubic_ids
        },
        "lower_bound_certificate": lower_bound,
        "minimum_size": len(minimum_sets[0]),
        "minimum_set_count": len(minimum_sets),
        "minimum_sets": minimum_sets,
    }


def write_json(path: Path, value: object) -> None:
    with open(native_path(path), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with open(native_path(path), "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def emit_csvs(
    output: Path,
    coordinate_document: dict[str, object],
    pattern_document: dict[str, object],
    collision_document: dict[str, object],
    witness_document: dict[str, object],
    minimum_document: dict[str, object],
) -> None:
    coordinate_rows_csv: list[dict[str, object]] = []
    for group_entry in list(coordinate_document["groups"]):
        for row in list(group_entry["rows"]):
            coordinate_rows_csv.append(
                {
                    "group": row["group"],
                    "coordinate_id": row["coordinate_id"],
                    "degree": row["degree"],
                    "degree_index": row["degree_index"],
                    "canonical_support_mask": row["canonical_support_mask"],
                    "support_arc_indices": compact(row["support_arc_indices"]),
                    "orbit_size": row["orbit_size"],
                    "setwise_stabilizer_order": row["setwise_stabilizer_order"],
                }
            )
    write_csv(
        output / "normalized_coordinate_registry.csv",
        [
            "group", "coordinate_id", "degree", "degree_index",
            "canonical_support_mask", "support_arc_indices", "orbit_size",
            "setwise_stabilizer_order",
        ],
        coordinate_rows_csv,
    )

    pattern_rows_csv: list[dict[str, object]] = []
    for group_entry in list(pattern_document["groups"]):
        for row in list(group_entry["rows"]):
            pattern_rows_csv.append(
                {
                    "group": row["group"],
                    "pattern_id": row["pattern_id"],
                    "canonical_mask": row["canonical_mask"],
                    "selected_arc_indices": compact(row["selected_arc_indices"]),
                    "orbit_size": row["orbit_size"],
                    "setwise_stabilizer_order": row["setwise_stabilizer_order"],
                    "signature_through_1": compact(row["signature_through_1"]),
                    "signature_through_2": compact(row["signature_through_2"]),
                    "signature_through_3": compact(row["signature_through_3"]),
                }
            )
    write_csv(
        output / "normalized_pattern_registry.csv",
        [
            "group", "pattern_id", "canonical_mask", "selected_arc_indices",
            "orbit_size", "setwise_stabilizer_order", "signature_through_1",
            "signature_through_2", "signature_through_3",
        ],
        pattern_rows_csv,
    )

    collision_rows_csv: list[dict[str, object]] = []
    for group_entry in list(collision_document["groups"]):
        for row in list(group_entry["rows"]):
            collision_rows_csv.append(
                {
                    "group": row["group"],
                    "fibre_id": row["fibre_id"],
                    "fibre_size": row["fibre_size"],
                    "signature_through_2": compact(row["signature_through_2"]),
                    "pattern_ids": compact(row["pattern_ids"]),
                    "canonical_masks": compact(row["canonical_masks"]),
                }
            )
    write_csv(
        output / "normalized_quadratic_collision_atlas.csv",
        ["group", "fibre_id", "fibre_size", "signature_through_2", "pattern_ids", "canonical_masks"],
        collision_rows_csv,
    )

    witness_rows_csv: list[dict[str, object]] = []
    for group_entry in list(witness_document["groups"]):
        for row in list(group_entry["rows"]):
            witness_rows_csv.append(
                {
                    "group": row["group"],
                    "pair_id": row["pair_id"],
                    "fibre_id": row["fibre_id"],
                    "left_pattern_id": row["left_pattern_id"],
                    "right_pattern_id": row["right_pattern_id"],
                    "left_mask": row["left_mask"],
                    "right_mask": row["right_mask"],
                    "selected_coordinate_id": row["selected_coordinate_id"],
                    "separating_coordinate_ids": compact(
                        [entry["coordinate_id"] for entry in list(row["separating_coordinates"])]
                    ),
                }
            )
    write_csv(
        output / "normalized_cubic_witness_map.csv",
        [
            "group", "pair_id", "fibre_id", "left_pattern_id",
            "right_pattern_id", "left_mask", "right_mask",
            "selected_coordinate_id", "separating_coordinate_ids",
        ],
        witness_rows_csv,
    )

    minimum_rows_csv: list[dict[str, object]] = []
    for group_entry in list(minimum_document["groups"]):
        for index, coordinate_ids in enumerate(list(group_entry["minimum_sets"])):
            minimum_rows_csv.append(
                {
                    "group": group_entry["group"],
                    "minimum_size": group_entry["minimum_size"],
                    "minimum_set_count": group_entry["minimum_set_count"],
                    "minimum_set_index": index,
                    "coordinate_ids": compact(coordinate_ids),
                }
            )
    write_csv(
        output / "normalized_conditional_minimum_extensions.csv",
        ["group", "minimum_size", "minimum_set_count", "minimum_set_index", "coordinate_ids"],
        minimum_rows_csv,
    )


def validate_ids(coordinates: list[dict[str, object]], patterns: list[dict[str, object]]) -> None:
    coordinate_re = re.compile(r"^(S4|A4)-D[123]-C[0-9]{3}$")
    pattern_re = re.compile(r"^(S4|A4)-P[0-9]{3}$")
    if not all(coordinate_re.fullmatch(str(row["coordinate_id"])) for row in coordinates):
        raise RuntimeError("coordinate ID grammar failure")
    if not all(pattern_re.fullmatch(str(row["pattern_id"])) for row in patterns):
        raise RuntimeError("pattern ID grammar failure")


def run(output: Path) -> dict[str, object]:
    started = time.perf_counter()
    input_hashes = verify_inputs()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    groups = build_groups()
    coordinate_groups: list[dict[str, object]] = []
    pattern_groups: list[dict[str, object]] = []
    collision_groups: list[dict[str, object]] = []
    witness_groups: list[dict[str, object]] = []
    minimum_groups: list[dict[str, object]] = []
    summary: dict[str, object] = {}

    for group in GROUP_ORDER:
        permutations = groups[group]
        actions = tuple(arc_action(permutation) for permutation in permutations)
        coordinates = coordinate_rows(group, permutations, actions)
        patterns = pattern_rows(group, permutations, actions, coordinates)
        validate_ids(coordinates, patterns)
        collisions, collision_entry = collision_rows(group, patterns)
        witnesses, witness_entry = witness_rows(group, collisions, patterns, coordinates)
        minimum_entry = minimum_extension(group, witnesses, coordinates)
        degree_counts = {
            str(degree): sum(int(row["degree"]) == degree for row in coordinates)
            for degree in (1, 2, 3)
        }
        cubic_signatures: dict[tuple[int, ...], int] = {}
        for pattern in patterns:
            key = tuple(int(value) for value in list(pattern["signature_through_3"]))
            cubic_signatures[key] = cubic_signatures.get(key, 0) + 1
        cubic_collision_fibres = sum(count > 1 for count in cubic_signatures.values())
        coordinate_groups.append(
            {
                "group": group,
                "group_order": len(permutations),
                "carrier_size": len(ARCS),
                "degree_counts": degree_counts,
                "rows": coordinates,
            }
        )
        pattern_groups.append(
            {
                "group": group,
                "group_order": len(permutations),
                "pattern_count": len(patterns),
                "rows": patterns,
            }
        )
        collision_groups.append(collision_entry)
        witness_groups.append(witness_entry)
        minimum_groups.append(minimum_entry)
        summary[group] = {
            "group_order": len(permutations),
            "pattern_orbits": len(patterns),
            "squarefree_degree_counts": [degree_counts[str(degree)] for degree in (1, 2, 3)],
            "quadratic_collision_fibres": collision_entry["collision_fibre_count"],
            "quadratic_colliding_classes": collision_entry["colliding_class_count"],
            "quadratic_colliding_pairs": collision_entry["colliding_pair_count"],
            "quadratic_max_fibre": collision_entry["max_fibre_size"],
            "cubic_collision_fibres": cubic_collision_fibres,
            "conditional_minimum_size": minimum_entry["minimum_size"],
            "conditional_minimum_set_count": minimum_entry["minimum_set_count"],
        }

    coordinate_document = {
        "schema_version": "orbit_atlas_coordinate_registry_v1",
        "experiment_id": EXPERIMENT_ID,
        "groups": coordinate_groups,
    }
    pattern_document = {
        "schema_version": "orbit_atlas_pattern_registry_v1",
        "experiment_id": EXPERIMENT_ID,
        "groups": pattern_groups,
    }
    collision_document = {
        "schema_version": "orbit_atlas_quadratic_collision_atlas_v1",
        "experiment_id": EXPERIMENT_ID,
        "groups": collision_groups,
    }
    witness_document = {
        "schema_version": "orbit_atlas_cubic_witness_map_v1",
        "experiment_id": EXPERIMENT_ID,
        "groups": witness_groups,
    }
    minimum_document = {
        "schema_version": "orbit_atlas_conditional_minimum_extensions_v1",
        "experiment_id": EXPERIMENT_ID,
        "scope": "all_degree_one_and_two_coordinates_retained_minimize_added_degree_three_coordinates",
        "groups": minimum_groups,
    }
    documents = {
        "coordinate_registry.json": coordinate_document,
        "pattern_registry.json": pattern_document,
        "quadratic_collision_atlas.json": collision_document,
        "cubic_witness_map.json": witness_document,
        "conditional_minimum_extensions.json": minimum_document,
    }
    for filename, document in documents.items():
        write_json(output / filename, document)
    emit_csvs(
        output,
        coordinate_document,
        pattern_document,
        collision_document,
        witness_document,
        minimum_document,
    )
    artifact_hashes = {filename: sha256(output / filename) for filename in SCIENTIFIC_FILES}
    build_summary = {
        "schema_version": "orbit_atlas_build_summary_v1",
        "experiment_id": EXPERIMENT_ID,
        "implementation_id": IMPLEMENTATION_ID,
        "implementation": "generator_closure_plus_lexicographic_orbit_minimum",
        "independence_declaration": {
            "shared_scientific_code": [],
            "consumed_other_implementation": False,
        },
        "input_hashes": input_hashes,
        "artifact_hashes": artifact_hashes,
        "summary": summary,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "random_seed": None,
        "verdict": "PASS",
    }
    write_json(output / "build_summary.json", build_summary)
    return build_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        build_summary = run(output)
    except Exception as exc:  # fail closed with a stable endpoint
        print(f"ORBIT_ATLAS_PRIMARY_FAIL|{type(exc).__name__}|{exc}")
        return 1
    print(
        "ORBIT_ATLAS_PRIMARY_PASS|"
        f"S4={build_summary['summary']['S4']}|A4={build_summary['summary']['A4']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
