#!/usr/bin/env python3
"""Independent four-vertex orbit-atlas generator.

This implementation enumerates S4/A4 directly, builds orbit partitions with
disjoint-set union, and uses bitset coverage for the conditional minimum.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from itertools import combinations, permutations
import json
import math
import os
from pathlib import Path
import re
import time


PROJECT = Path(__file__).resolve().parents[1]
EXPERIMENT = "ORBIT_ATLAS"
IMPLEMENTATION_ID = "INDEPENDENT_ENUMERATION"
INPUTS = {
    "normalization": PROJECT / "docs" / "NORMALIZATION_LOCK.md",
    "machine_contract": PROJECT / "schemas" / "orbit_atlas_contract_v1.json",
    "specification": PROJECT / "schemas" / "orbit_atlas_specification.yaml",
}
GROUP_SEQUENCE = ("S4", "A4")
POINTS = (0, 1, 2, 3)
EDGE_LIST = tuple((tail, head) for tail in POINTS for head in POINTS if tail != head)
EDGE_TO_BIT = {edge: bit for bit, edge in enumerate(EDGE_LIST)}
ARTIFACT_NAMES = (
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


class DisjointSets:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != item:
            successor = self.parent[item]
            self.parent[item] = root
            item = successor
        return root

    def merge(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def file_hash(path: Path) -> str:
    state = hashlib.sha256()
    with open(native_path(path), "rb") as stream:
        while True:
            data = stream.read(65536)
            if not data:
                break
            state.update(data)
    return state.hexdigest()


def input_hashes() -> dict[str, str]:
    missing = [str(path) for path in INPUTS.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing specification inputs: {missing}")
    return {label: file_hash(path) for label, path in INPUTS.items()}


def even_permutation(permutation: tuple[int, ...]) -> bool:
    inversions = sum(
        permutation[left] > permutation[right]
        for left in range(4)
        for right in range(left + 1, 4)
    )
    return inversions % 2 == 0


def enumerate_groups() -> dict[str, tuple[tuple[int, ...], ...]]:
    symmetric = tuple(tuple(item) for item in permutations(POINTS))
    alternating = tuple(item for item in symmetric if even_permutation(item))
    if len(symmetric) != 24 or len(alternating) != 12:
        raise ValueError("direct group enumeration failed")
    return {"S4": symmetric, "A4": alternating}


def induced_edge_map(permutation: tuple[int, ...]) -> tuple[int, ...]:
    transformed: list[int] = []
    for tail, head in EDGE_LIST:
        transformed.append(EDGE_TO_BIT[(permutation[tail], permutation[head])])
    return tuple(transformed)


def transform(value: int, edge_map: tuple[int, ...]) -> int:
    result = 0
    bit = 0
    remainder = value
    while remainder:
        if remainder & 1:
            result |= 1 << edge_map[bit]
        remainder >>= 1
        bit += 1
    return result


def indices(value: int) -> list[int]:
    return [bit for bit in range(12) if (value >> bit) & 1]


def arcs(value: int) -> list[list[int]]:
    return [list(EDGE_LIST[bit]) for bit in indices(value)]


def mask_from_indices(items: tuple[int, ...]) -> int:
    return sum(1 << item for item in items)


def partition_values(values: list[int], edge_maps: tuple[tuple[int, ...], ...]) -> list[list[int]]:
    location = {value: index for index, value in enumerate(values)}
    dsu = DisjointSets(len(values))
    for value_index, value in enumerate(values):
        for edge_map in edge_maps:
            dsu.merge(value_index, location[transform(value, edge_map)])
    buckets: dict[int, list[int]] = {}
    for value_index, value in enumerate(values):
        buckets.setdefault(dsu.find(value_index), []).append(value)
    components = [sorted(component) for component in buckets.values()]
    components.sort(key=lambda component: component[0])
    return components


def build_coordinate_table(
    group_name: str,
    group_elements: tuple[tuple[int, ...], ...],
    edge_maps: tuple[tuple[int, ...], ...],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for degree in (1, 2, 3):
        universe = [mask_from_indices(choice) for choice in combinations(range(12), degree)]
        components = partition_values(universe, edge_maps)
        for local_index, component in enumerate(components):
            representative = component[0]
            stabilizer = sum(transform(representative, edge_map) == representative for edge_map in edge_maps)
            if stabilizer * len(component) != len(group_elements):
                raise ValueError("coordinate partition violates orbit-stabilizer")
            result.append(
                {
                    "group": group_name,
                    "coordinate_id": f"{group_name}-D{degree}-C{local_index:03d}",
                    "degree": degree,
                    "degree_index": local_index,
                    "canonical_support_mask": representative,
                    "canonical_support_hex": f"0x{representative:03x}",
                    "support_arc_indices": indices(representative),
                    "support_arcs": arcs(representative),
                    "support_orbit_masks": component,
                    "orbit_size": len(component),
                    "setwise_stabilizer_order": stabilizer,
                }
            )
    return result


def build_pattern_table(
    group_name: str,
    group_elements: tuple[tuple[int, ...], ...],
    edge_maps: tuple[tuple[int, ...], ...],
    coordinates: list[dict[str, object]],
) -> list[dict[str, object]]:
    components = partition_values(list(range(4096)), edge_maps)
    limits = {
        degree: sum(int(row["degree"]) <= degree for row in coordinates)
        for degree in (1, 2, 3)
    }

    def full_signature(pattern: int) -> list[int]:
        values: list[int] = []
        for coordinate in coordinates:
            support_masks = list(coordinate["support_orbit_masks"])
            values.append(sum((support & pattern) == support for support in support_masks))
        return values

    result: list[dict[str, object]] = []
    for local_index, component in enumerate(components):
        representative = component[0]
        stabilizer = sum(transform(representative, edge_map) == representative for edge_map in edge_maps)
        if stabilizer * len(component) != len(group_elements):
            raise ValueError("pattern partition violates orbit-stabilizer")
        signature = full_signature(representative)
        result.append(
            {
                "group": group_name,
                "pattern_id": f"{group_name}-P{local_index:03d}",
                "representative_mask": representative,
                "canonical_mask": representative,
                "canonical_hex": f"0x{representative:03x}",
                "selected_arc_indices": indices(representative),
                "selected_arcs": arcs(representative),
                "orbit_masks": component,
                "orbit_size": len(component),
                "setwise_stabilizer_order": stabilizer,
                "signature_through_1": signature[: limits[1]],
                "signature_through_2": signature[: limits[2]],
                "signature_through_3": signature[: limits[3]],
            }
        )
    if sorted(value for row in result for value in list(row["orbit_masks"])) != list(range(4096)):
        raise ValueError("pattern partition is incomplete")
    return result


def build_collision_table(group_name: str, patterns: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    buckets: dict[tuple[int, ...], list[dict[str, object]]] = {}
    for pattern in patterns:
        signature = tuple(int(item) for item in list(pattern["signature_through_2"]))
        buckets.setdefault(signature, []).append(pattern)
    nontrivial: list[tuple[tuple[int, ...], list[dict[str, object]]]] = []
    for signature, members in buckets.items():
        if len(members) > 1:
            nontrivial.append((signature, sorted(members, key=lambda item: int(item["canonical_mask"]))))
    nontrivial.sort(key=lambda item: (item[0], [int(row["canonical_mask"]) for row in item[1]]))
    rows: list[dict[str, object]] = []
    for local_index, (signature, members) in enumerate(nontrivial):
        rows.append(
            {
                "group": group_name,
                "fibre_id": f"{group_name}-QF{local_index:03d}",
                "signature_through_2": list(signature),
                "pattern_ids": [str(member["pattern_id"]) for member in members],
                "canonical_masks": [int(member["canonical_mask"]) for member in members],
                "fibre_size": len(members),
            }
        )
    group_record = {
        "group": group_name,
        "collision_fibre_count": len(rows),
        "colliding_class_count": sum(int(row["fibre_size"]) for row in rows),
        "colliding_pair_count": sum(math.comb(int(row["fibre_size"]), 2) for row in rows),
        "max_fibre_size": max((int(row["fibre_size"]) for row in rows), default=1),
        "rows": rows,
    }
    return rows, group_record


def build_witness_table(
    group_name: str,
    fibres: list[dict[str, object]],
    patterns: list[dict[str, object]],
    coordinates: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    lookup = {str(row["pattern_id"]): row for row in patterns}
    cubic = [row for row in coordinates if int(row["degree"]) == 3]
    prefix_length = len(coordinates) - len(cubic)
    rows: list[dict[str, object]] = []
    for fibre in fibres:
        members = [lookup[item] for item in list(fibre["pattern_ids"])]
        for left, right in combinations(members, 2):
            separators: list[dict[str, object]] = []
            left_signature = list(left["signature_through_3"])[prefix_length:]
            right_signature = list(right["signature_through_3"])[prefix_length:]
            for coordinate, left_value, right_value in zip(cubic, left_signature, right_signature, strict=True):
                if int(left_value) != int(right_value):
                    separators.append(
                        {
                            "coordinate_id": str(coordinate["coordinate_id"]),
                            "left_value": int(left_value),
                            "right_value": int(right_value),
                        }
                    )
            if not separators:
                raise ValueError("cubic coordinates do not resolve a quadratic pair")
            rows.append(
                {
                    "group": group_name,
                    "fibre_id": str(fibre["fibre_id"]),
                    "left_pattern_id": str(left["pattern_id"]),
                    "right_pattern_id": str(right["pattern_id"]),
                    "left_mask": int(left["canonical_mask"]),
                    "right_mask": int(right["canonical_mask"]),
                    "separating_coordinates": separators,
                    "selected_coordinate_id": str(separators[0]["coordinate_id"]),
                }
            )
    rows.sort(key=lambda item: (int(item["left_mask"]), int(item["right_mask"])))
    completed: list[dict[str, object]] = []
    for local_index, row in enumerate(rows):
        completed.append(
            {
                "group": row["group"],
                "pair_id": f"{group_name}-QP{local_index:03d}",
                "fibre_id": row["fibre_id"],
                "left_pattern_id": row["left_pattern_id"],
                "right_pattern_id": row["right_pattern_id"],
                "left_mask": row["left_mask"],
                "right_mask": row["right_mask"],
                "separating_coordinates": row["separating_coordinates"],
                "selected_coordinate_id": row["selected_coordinate_id"],
            }
        )
    return completed, {"group": group_name, "colliding_pair_count": len(completed), "rows": completed}


def bitset_minimum(
    group_name: str,
    witnesses: list[dict[str, object]],
    coordinates: list[dict[str, object]],
) -> dict[str, object]:
    coordinate_ids = [str(row["coordinate_id"]) for row in coordinates if int(row["degree"]) == 3]
    pair_ids = [str(row["pair_id"]) for row in witnesses]
    pair_position = {pair_id: position for position, pair_id in enumerate(pair_ids)}
    coverage_bits = {coordinate_id: 0 for coordinate_id in coordinate_ids}
    coverage_lists = {coordinate_id: [] for coordinate_id in coordinate_ids}
    for witness in witnesses:
        pair_id = str(witness["pair_id"])
        bit = 1 << pair_position[pair_id]
        for separator in list(witness["separating_coordinates"]):
            coordinate_id = str(separator["coordinate_id"])
            coverage_bits[coordinate_id] |= bit
            coverage_lists[coordinate_id].append(pair_id)
    complete = (1 << len(pair_ids)) - 1
    certificate: list[dict[str, int]] = []
    winning: list[list[str]] = []
    for size in range(len(coordinate_ids) + 1):
        tested = 0
        for choice in combinations(coordinate_ids, size):
            tested += 1
            union = 0
            for coordinate_id in choice:
                union |= coverage_bits[coordinate_id]
            if union == complete:
                winning.append(list(choice))
        certificate.append(
            {
                "size": size,
                "tested_subset_count": tested,
                "separating_subset_count": len(winning),
            }
        )
        if winning:
            break
    if not winning:
        raise ValueError("bitset enumeration found no separating extension")
    return {
        "group": group_name,
        "cubic_coordinate_ids": coordinate_ids,
        "collision_pair_ids": pair_ids,
        "coverage_by_coordinate": {
            coordinate_id: coverage_lists[coordinate_id] for coordinate_id in coordinate_ids
        },
        "lower_bound_certificate": certificate,
        "minimum_size": len(winning[0]),
        "minimum_set_count": len(winning),
        "minimum_sets": winning,
    }


def save_json(path: Path, value: object) -> None:
    serialized = json.dumps(value, sort_keys=True, indent=2) + "\n"
    with open(native_path(path), "w", encoding="utf-8", newline="\n") as stream:
        stream.write(serialized)


def encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def save_csv(path: Path, columns: list[str], records: list[dict[str, object]]) -> None:
    with open(native_path(path), "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def create_csv_projections(
    output: Path,
    coordinate_document: dict[str, object],
    pattern_document: dict[str, object],
    collision_document: dict[str, object],
    witness_document: dict[str, object],
    minimum_document: dict[str, object],
) -> None:
    coordinate_records: list[dict[str, object]] = []
    for group in list(coordinate_document["groups"]):
        for row in list(group["rows"]):
            coordinate_records.append(
                {
                    "group": row["group"],
                    "coordinate_id": row["coordinate_id"],
                    "degree": row["degree"],
                    "degree_index": row["degree_index"],
                    "canonical_support_mask": row["canonical_support_mask"],
                    "support_arc_indices": encoded(row["support_arc_indices"]),
                    "orbit_size": row["orbit_size"],
                    "setwise_stabilizer_order": row["setwise_stabilizer_order"],
                }
            )
    save_csv(
        output / "normalized_coordinate_registry.csv",
        [
            "group", "coordinate_id", "degree", "degree_index",
            "canonical_support_mask", "support_arc_indices", "orbit_size",
            "setwise_stabilizer_order",
        ],
        coordinate_records,
    )

    pattern_records: list[dict[str, object]] = []
    for group in list(pattern_document["groups"]):
        for row in list(group["rows"]):
            pattern_records.append(
                {
                    "group": row["group"],
                    "pattern_id": row["pattern_id"],
                    "canonical_mask": row["canonical_mask"],
                    "selected_arc_indices": encoded(row["selected_arc_indices"]),
                    "orbit_size": row["orbit_size"],
                    "setwise_stabilizer_order": row["setwise_stabilizer_order"],
                    "signature_through_1": encoded(row["signature_through_1"]),
                    "signature_through_2": encoded(row["signature_through_2"]),
                    "signature_through_3": encoded(row["signature_through_3"]),
                }
            )
    save_csv(
        output / "normalized_pattern_registry.csv",
        [
            "group", "pattern_id", "canonical_mask", "selected_arc_indices",
            "orbit_size", "setwise_stabilizer_order", "signature_through_1",
            "signature_through_2", "signature_through_3",
        ],
        pattern_records,
    )

    collision_records: list[dict[str, object]] = []
    for group in list(collision_document["groups"]):
        for row in list(group["rows"]):
            collision_records.append(
                {
                    "group": row["group"],
                    "fibre_id": row["fibre_id"],
                    "fibre_size": row["fibre_size"],
                    "signature_through_2": encoded(row["signature_through_2"]),
                    "pattern_ids": encoded(row["pattern_ids"]),
                    "canonical_masks": encoded(row["canonical_masks"]),
                }
            )
    save_csv(
        output / "normalized_quadratic_collision_atlas.csv",
        ["group", "fibre_id", "fibre_size", "signature_through_2", "pattern_ids", "canonical_masks"],
        collision_records,
    )

    witness_records: list[dict[str, object]] = []
    for group in list(witness_document["groups"]):
        for row in list(group["rows"]):
            witness_records.append(
                {
                    "group": row["group"],
                    "pair_id": row["pair_id"],
                    "fibre_id": row["fibre_id"],
                    "left_pattern_id": row["left_pattern_id"],
                    "right_pattern_id": row["right_pattern_id"],
                    "left_mask": row["left_mask"],
                    "right_mask": row["right_mask"],
                    "selected_coordinate_id": row["selected_coordinate_id"],
                    "separating_coordinate_ids": encoded(
                        [item["coordinate_id"] for item in list(row["separating_coordinates"])]
                    ),
                }
            )
    save_csv(
        output / "normalized_cubic_witness_map.csv",
        [
            "group", "pair_id", "fibre_id", "left_pattern_id",
            "right_pattern_id", "left_mask", "right_mask",
            "selected_coordinate_id", "separating_coordinate_ids",
        ],
        witness_records,
    )

    minimum_records: list[dict[str, object]] = []
    for group in list(minimum_document["groups"]):
        for local_index, coordinate_ids in enumerate(list(group["minimum_sets"])):
            minimum_records.append(
                {
                    "group": group["group"],
                    "minimum_size": group["minimum_size"],
                    "minimum_set_count": group["minimum_set_count"],
                    "minimum_set_index": local_index,
                    "coordinate_ids": encoded(coordinate_ids),
                }
            )
    save_csv(
        output / "normalized_conditional_minimum_extensions.csv",
        ["group", "minimum_size", "minimum_set_count", "minimum_set_index", "coordinate_ids"],
        minimum_records,
    )


def enforce_id_grammar(coordinates: list[dict[str, object]], patterns: list[dict[str, object]]) -> None:
    coordinate_pattern = re.compile(r"^(S4|A4)-D[123]-C[0-9]{3}$")
    pattern_pattern = re.compile(r"^(S4|A4)-P[0-9]{3}$")
    for row in coordinates:
        if coordinate_pattern.fullmatch(str(row["coordinate_id"])) is None:
            raise ValueError("coordinate identifier violates the frozen grammar")
    for row in patterns:
        if pattern_pattern.fullmatch(str(row["pattern_id"])) is None:
            raise ValueError("pattern identifier violates the frozen grammar")


def execute(output: Path) -> dict[str, object]:
    clock = time.perf_counter()
    observed_input_hashes = input_hashes()
    if output.exists() and next(output.iterdir(), None) is not None:
        raise FileExistsError(f"refusing nonempty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    groups = enumerate_groups()
    coordinate_groups: list[dict[str, object]] = []
    pattern_groups: list[dict[str, object]] = []
    collision_groups: list[dict[str, object]] = []
    witness_groups: list[dict[str, object]] = []
    minimum_groups: list[dict[str, object]] = []
    summary: dict[str, object] = {}

    for group_name in GROUP_SEQUENCE:
        group_elements = groups[group_name]
        edge_maps = tuple(induced_edge_map(item) for item in group_elements)
        coordinates = build_coordinate_table(group_name, group_elements, edge_maps)
        patterns = build_pattern_table(group_name, group_elements, edge_maps, coordinates)
        enforce_id_grammar(coordinates, patterns)
        collision_rows, collision_group = build_collision_table(group_name, patterns)
        witness_rows, witness_group = build_witness_table(
            group_name, collision_rows, patterns, coordinates
        )
        minimum_group = bitset_minimum(group_name, witness_rows, coordinates)
        counts = {
            str(degree): sum(int(row["degree"]) == degree for row in coordinates)
            for degree in (1, 2, 3)
        }
        cubic_buckets: dict[tuple[int, ...], int] = {}
        for pattern in patterns:
            signature = tuple(int(item) for item in list(pattern["signature_through_3"]))
            cubic_buckets[signature] = cubic_buckets.get(signature, 0) + 1
        cubic_collisions = sum(size > 1 for size in cubic_buckets.values())
        coordinate_groups.append(
            {
                "group": group_name,
                "group_order": len(group_elements),
                "carrier_size": len(EDGE_LIST),
                "degree_counts": counts,
                "rows": coordinates,
            }
        )
        pattern_groups.append(
            {
                "group": group_name,
                "group_order": len(group_elements),
                "pattern_count": len(patterns),
                "rows": patterns,
            }
        )
        collision_groups.append(collision_group)
        witness_groups.append(witness_group)
        minimum_groups.append(minimum_group)
        summary[group_name] = {
            "group_order": len(group_elements),
            "pattern_orbits": len(patterns),
            "squarefree_degree_counts": [counts[str(degree)] for degree in (1, 2, 3)],
            "quadratic_collision_fibres": collision_group["collision_fibre_count"],
            "quadratic_colliding_classes": collision_group["colliding_class_count"],
            "quadratic_colliding_pairs": collision_group["colliding_pair_count"],
            "quadratic_max_fibre": collision_group["max_fibre_size"],
            "cubic_collision_fibres": cubic_collisions,
            "conditional_minimum_size": minimum_group["minimum_size"],
            "conditional_minimum_set_count": minimum_group["minimum_set_count"],
        }

    coordinate_document = {
        "schema_version": "orbit_atlas_coordinate_registry_v1",
        "experiment_id": EXPERIMENT,
        "groups": coordinate_groups,
    }
    pattern_document = {
        "schema_version": "orbit_atlas_pattern_registry_v1",
        "experiment_id": EXPERIMENT,
        "groups": pattern_groups,
    }
    collision_document = {
        "schema_version": "orbit_atlas_quadratic_collision_atlas_v1",
        "experiment_id": EXPERIMENT,
        "groups": collision_groups,
    }
    witness_document = {
        "schema_version": "orbit_atlas_cubic_witness_map_v1",
        "experiment_id": EXPERIMENT,
        "groups": witness_groups,
    }
    minimum_document = {
        "schema_version": "orbit_atlas_conditional_minimum_extensions_v1",
        "experiment_id": EXPERIMENT,
        "scope": "all_degree_one_and_two_coordinates_retained_minimize_added_degree_three_coordinates",
        "groups": minimum_groups,
    }
    for filename, document in (
        ("coordinate_registry.json", coordinate_document),
        ("pattern_registry.json", pattern_document),
        ("quadratic_collision_atlas.json", collision_document),
        ("cubic_witness_map.json", witness_document),
        ("conditional_minimum_extensions.json", minimum_document),
    ):
        save_json(output / filename, document)
    create_csv_projections(
        output,
        coordinate_document,
        pattern_document,
        collision_document,
        witness_document,
        minimum_document,
    )
    artifact_hashes = {name: file_hash(output / name) for name in ARTIFACT_NAMES}
    build_summary = {
        "schema_version": "orbit_atlas_build_summary_v1",
        "experiment_id": EXPERIMENT,
        "implementation_id": IMPLEMENTATION_ID,
        "implementation": "full_permutation_enumeration_plus_disjoint_set_partitions",
        "independence_declaration": {
            "shared_scientific_code": [],
            "consumed_other_implementation": False,
        },
        "input_hashes": observed_input_hashes,
        "artifact_hashes": artifact_hashes,
        "summary": summary,
        "runtime_seconds": round(time.perf_counter() - clock, 6),
        "random_seed": None,
        "verdict": "PASS",
    }
    save_json(output / "build_summary.json", build_summary)
    return build_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    namespace = parser.parse_args()
    destination = namespace.output if namespace.output.is_absolute() else PROJECT / namespace.output
    try:
        build_summary = execute(destination)
    except Exception as error:
        print(f"ORBIT_ATLAS_INDEPENDENT_FAIL|{type(error).__name__}|{error}")
        return 1
    print(
        "ORBIT_ATLAS_INDEPENDENT_PASS|"
        f"S4={build_summary['summary']['S4']}|A4={build_summary['summary']['A4']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
