#!/usr/bin/env python3
"""From-definition reconstruction of the canonical four-action payload.

The implementation is self-contained: it imports no generated mask table,
solver instance, or independent-checker module.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


SCHEMA = "orbit_sum_canonical_payload_v1"
EXPERIMENT_ID = (
    "FOUR_FIVE_VERTEX_ORBIT_SUM_RECONSTRUCTION"
)


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_canonical_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def permutation_parity(permutation: Sequence[int]) -> int:
    inversions = sum(
        permutation[i] > permutation[j]
        for i in range(len(permutation))
        for j in range(i + 1, len(permutation))
    )
    return inversions & 1


def group_permutations(n: int, alternating: bool) -> tuple[tuple[int, ...], ...]:
    permutations = tuple(itertools.permutations(range(n)))
    if alternating:
        permutations = tuple(p for p in permutations if permutation_parity(p) == 0)
    expected = math.factorial(n) // (2 if alternating else 1)
    if len(permutations) != expected:
        raise AssertionError("finite-group enumeration failed")
    return permutations


def carrier(n: int) -> tuple[tuple[int, int], ...]:
    return tuple((i, j) for i in range(n) for j in range(n) if i != j)


def induced_arc_map(
    arcs: Sequence[tuple[int, int]], permutation: Sequence[int]
) -> tuple[int, ...]:
    index = {arc: position for position, arc in enumerate(arcs)}
    return tuple(index[(permutation[i], permutation[j])] for i, j in arcs)


def transpose_arc_map(arcs: Sequence[tuple[int, int]]) -> tuple[int, ...]:
    index = {arc: position for position, arc in enumerate(arcs)}
    return tuple(index[(j, i)] for i, j in arcs)


def transform_mask(mask: int, arc_map: Sequence[int]) -> int:
    transformed = 0
    remaining = mask
    while remaining:
        least = remaining & -remaining
        source = least.bit_length() - 1
        transformed |= 1 << arc_map[source]
        remaining ^= least
    return transformed


def orbit_of_mask(mask: int, arc_maps: Sequence[Sequence[int]]) -> tuple[int, ...]:
    return tuple(sorted({transform_mask(mask, action) for action in arc_maps}))


def fixed_hex(mask: int, width: int) -> str:
    return f"{mask:0{width}x}"


@dataclass(frozen=True)
class Coordinate:
    degree: int
    representative: int
    orbit: tuple[int, ...]


@dataclass
class Model:
    n: int
    group_name: str
    arcs: tuple[tuple[int, int], ...]
    permutations: tuple[tuple[int, ...], ...]
    arc_maps: tuple[tuple[int, ...], ...]
    pattern_representatives: tuple[int, ...]
    coordinates: tuple[Coordinate, ...]
    values: tuple[tuple[int, ...], ...]

    @property
    def width(self) -> int:
        return math.ceil(len(self.arcs) / 4)

    def pattern_id(self, mask: int) -> str:
        return f"{self.group_name}:{self.n}:{fixed_hex(mask, self.width)}"

    def coordinate_id(self, coordinate: Coordinate) -> str:
        return (
            f"{self.group_name}:{self.n}:{coordinate.degree}:"
            f"{fixed_hex(coordinate.representative, self.width)}"
        )


def enumerate_pattern_representatives(
    arc_count: int, arc_maps: Sequence[Sequence[int]]
) -> tuple[int, ...]:
    seen = bytearray(1 << arc_count)
    representatives: list[int] = []
    for mask in range(1 << arc_count):
        if seen[mask]:
            continue
        orbit = orbit_of_mask(mask, arc_maps)
        representative = orbit[0]
        if representative != mask:
            raise AssertionError("ascending orbit traversal lost canonical minimum")
        representatives.append(representative)
        for member in orbit:
            seen[member] = 1
    return tuple(representatives)


def enumerate_coordinates(
    arc_count: int, max_degree: int, arc_maps: Sequence[Sequence[int]]
) -> tuple[Coordinate, ...]:
    coordinates: list[Coordinate] = []
    for degree in range(1, max_degree + 1):
        seen: set[int] = set()
        degree_coordinates: list[Coordinate] = []
        for positions in itertools.combinations(range(arc_count), degree):
            mask = sum(1 << position for position in positions)
            if mask in seen:
                continue
            orbit = orbit_of_mask(mask, arc_maps)
            seen.update(orbit)
            degree_coordinates.append(Coordinate(degree, orbit[0], orbit))
        degree_coordinates.sort(key=lambda coordinate: coordinate.representative)
        coordinates.extend(degree_coordinates)
    return tuple(coordinates)


def evaluate_coordinate(pattern: int, coordinate: Coordinate) -> int:
    return sum((support & pattern) == support for support in coordinate.orbit)


def build_model(n: int, alternating: bool, max_degree: int) -> Model:
    group_name = f"{'A' if alternating else 'S'}{n}"
    arcs = carrier(n)
    permutations = group_permutations(n, alternating)
    arc_maps = tuple(induced_arc_map(arcs, p) for p in permutations)
    patterns = enumerate_pattern_representatives(len(arcs), arc_maps)
    coordinates = enumerate_coordinates(len(arcs), max_degree, arc_maps)
    values = tuple(
        tuple(evaluate_coordinate(pattern, coordinate) for coordinate in coordinates)
        for pattern in patterns
    )
    if len(set(values)) != len(values):
        raise AssertionError(f"degree {max_degree} is not injective for {group_name}")
    return Model(
        n=n,
        group_name=group_name,
        arcs=arcs,
        permutations=permutations,
        arc_maps=arc_maps,
        pattern_representatives=patterns,
        coordinates=coordinates,
        values=values,
    )


def prefix_length(model: Model, degree: int) -> int:
    return sum(coordinate.degree <= degree for coordinate in model.coordinates)


def residual_pairs(model: Model, degree: int) -> tuple[tuple[int, int], ...]:
    width = prefix_length(model, degree)
    cells: dict[tuple[int, ...], list[int]] = defaultdict(list)
    for index, row in enumerate(model.values):
        cells[row[:width]].append(index)
    return tuple(
        (left, right)
        for cell in cells.values()
        for left, right in itertools.combinations(cell, 2)
    )


def support_graph_data(
    arcs: Sequence[tuple[int, int]], support: int, n: int
) -> dict[str, object]:
    directed = [arcs[k] for k in range(len(arcs)) if support & (1 << k)]
    undirected = {tuple(sorted(arc)) for arc in directed}
    touched = sorted({vertex for edge in undirected for vertex in edge})
    adjacency = {vertex: set() for vertex in touched}
    for left, right in undirected:
        adjacency[left].add(right)
        adjacency[right].add(left)
    reached: set[int] = set()
    if touched:
        stack = [touched[0]]
        while stack:
            vertex = stack.pop()
            if vertex in reached:
                continue
            reached.add(vertex)
            stack.extend(adjacency[vertex] - reached)
    connected = bool(touched) and len(reached) == len(touched)
    tree = connected and len(touched) == n and len(undirected) == n - 1
    unicyclic = connected and len(undirected) == len(touched)
    indegree = [0] * n
    outdegree = [0] * n
    for left, right in directed:
        outdegree[left] += 1
        indegree[right] += 1
    undirected_degree = [0] * n
    for left, right in undirected:
        undirected_degree[left] += 1
        undirected_degree[right] += 1
    if tree:
        category = "TREE_ON_ALL_VERTICES"
    elif unicyclic:
        category = "UNICYCLIC_ON_TOUCHED_VERTICES"
    else:
        category = "OTHER"
    return {
        "category": category,
        "connected_on_touched_vertices": connected,
        "directed_arc_count": len(directed),
        "indegree_sequence": sorted(indegree, reverse=True),
        "outdegree_sequence": sorted(outdegree, reverse=True),
        "touched_vertex_count": len(touched),
        "undirected_degree_sequence": sorted(undirected_degree, reverse=True),
        "undirected_edge_count": len(undirected),
    }


def separation_data(
    model: Model, pairs: Sequence[tuple[int, int]], top_degree: int
) -> tuple[list[int], list[dict[str, object]], list[dict[str, object]]]:
    coordinate_indices = [
        index
        for index, coordinate in enumerate(model.coordinates)
        if coordinate.degree == top_degree
    ]
    pair_width = max(1, math.ceil(len(pairs) / 4))
    coordinate_pair_bits = [0] * len(coordinate_indices)
    pair_records: list[dict[str, object]] = []
    for pair_index, (left, right) in enumerate(pairs):
        separators: list[int] = []
        for local_index, coordinate_index in enumerate(coordinate_indices):
            if model.values[left][coordinate_index] != model.values[right][coordinate_index]:
                separators.append(local_index)
                coordinate_pair_bits[local_index] |= 1 << pair_index
        left_id = model.pattern_id(model.pattern_representatives[left])
        right_id = model.pattern_id(model.pattern_representatives[right])
        pair_records.append(
            {
                "pair_id": [left_id, right_id],
                "pattern_indices": [left, right],
                "separator_coordinate_ids": [
                    model.coordinate_id(model.coordinates[coordinate_indices[i]])
                    for i in separators
                ],
                "separator_local_mask_hex": fixed_hex(
                    sum(1 << i for i in separators),
                    max(1, math.ceil(len(coordinate_indices) / 4)),
                ),
            }
        )
    coordinate_records = [
        {
            "coordinate_id": model.coordinate_id(model.coordinates[coordinate_index]),
            "separated_pair_mask_hex": fixed_hex(bits, pair_width),
        }
        for coordinate_index, bits in zip(coordinate_indices, coordinate_pair_bits)
    ]
    return coordinate_pair_bits, pair_records, coordinate_records


def covering_subsets(
    cover_bits: Sequence[int], universe_size: int, allowed: Sequence[int] | None = None
) -> tuple[int | None, tuple[tuple[int, ...], ...]]:
    universe = (1 << universe_size) - 1
    candidates = tuple(range(len(cover_bits))) if allowed is None else tuple(allowed)
    if universe == 0:
        return 0, ((),)
    if not candidates or math.prod([1]) == 0:
        return None, ()
    aggregate = 0
    for index in candidates:
        aggregate |= cover_bits[index]
    if aggregate != universe:
        return None, ()
    for size in range(1, len(candidates) + 1):
        solutions: list[tuple[int, ...]] = []
        for choice in itertools.combinations(candidates, size):
            covered = 0
            for index in choice:
                covered |= cover_bits[index]
            if covered == universe:
                solutions.append(choice)
        if solutions:
            return size, tuple(solutions)
    raise AssertionError("finite covering search exhausted unexpectedly")


def recanonicalize(
    support: int, transform: Sequence[int], scientific_maps: Sequence[Sequence[int]]
) -> int:
    transformed = transform_mask(support, transform)
    return min(transform_mask(transformed, action) for action in scientific_maps)


def induced_external_maps(
    model: Model, local_coordinate_indices: Sequence[int]
) -> tuple[tuple[int, ...], ...]:
    local_lookup = {
        model.coordinates[coordinate_index].representative: local_index
        for local_index, coordinate_index in enumerate(local_coordinate_indices)
    }
    generators = [transpose_arc_map(model.arcs)]
    if model.group_name.startswith("A"):
        odd = tuple([1, 0] + list(range(2, model.n)))
        generators.append(induced_arc_map(model.arcs, odd))
    maps: list[tuple[int, ...]] = []
    for generator in generators:
        image: list[int] = []
        for coordinate_index in local_coordinate_indices:
            representative = model.coordinates[coordinate_index].representative
            canonical = recanonicalize(representative, generator, model.arc_maps)
            if canonical not in local_lookup:
                raise AssertionError("external action left the top-degree dictionary")
            image.append(local_lookup[canonical])
        if len(set(image)) != len(image):
            raise AssertionError("external generator is not a coordinate permutation")
        maps.append(tuple(image))
    return tuple(maps)


def solution_external_orbits(
    solutions: Sequence[tuple[int, ...]], generators: Sequence[Sequence[int]]
) -> tuple[tuple[tuple[int, ...], ...], ...]:
    solution_set = {tuple(sorted(solution)) for solution in solutions}
    unseen = set(solution_set)
    orbits: list[tuple[tuple[int, ...], ...]] = []
    while unseen:
        seed = min(unseen)
        orbit = {seed}
        stack = [seed]
        while stack:
            current = stack.pop()
            for generator in generators:
                image = tuple(sorted(generator[index] for index in current))
                if image not in solution_set:
                    raise AssertionError("external action left the solution set")
                if image not in orbit:
                    orbit.add(image)
                    stack.append(image)
        unseen.difference_update(orbit)
        orbits.append(tuple(sorted(orbit)))
    return tuple(sorted(orbits))


def sn_crosswalk(a_model: Model, s_model: Model) -> tuple[dict[int, int], list[dict[str, object]]]:
    if a_model.n != s_model.n:
        raise ValueError("crosswalk requires one carrier")
    mapping: dict[int, int] = {}
    buckets: dict[int, list[int]] = defaultdict(list)
    s_index_by_representative = {
        representative: index
        for index, representative in enumerate(s_model.pattern_representatives)
    }
    for a_index, representative in enumerate(a_model.pattern_representatives):
        s_representative = min(
            transform_mask(representative, action) for action in s_model.arc_maps
        )
        s_index = s_index_by_representative[s_representative]
        mapping[a_index] = s_index
        buckets[s_index].append(a_index)
    records = []
    for s_index in sorted(buckets):
        a_indices = buckets[s_index]
        records.append(
            {
                "S_orbit_id": s_model.pattern_id(s_model.pattern_representatives[s_index]),
                "A_orbit_ids": [
                    a_model.pattern_id(a_model.pattern_representatives[index])
                    for index in a_indices
                ],
                "splits": len(a_indices) == 2,
            }
        )
        if len(a_indices) not in (1, 2):
            raise AssertionError("index-two subgroup crosswalk multiplicity invalid")
    return mapping, records


def coordinate_metadata(model: Model) -> list[dict[str, object]]:
    return [
        {
            "coordinate_id": model.coordinate_id(coordinate),
            "degree": coordinate.degree,
            "orbit_size": len(coordinate.orbit),
            "representative_hex": fixed_hex(coordinate.representative, model.width),
            "support_class": support_graph_data(
                model.arcs, coordinate.representative, model.n
            ),
        }
        for coordinate in model.coordinates
    ]


def model_payload(model: Model, companion: Model | None) -> dict[str, object]:
    residual_degree = model.n - 2
    top_degree = model.n - 1
    pairs = residual_pairs(model, residual_degree)
    cover_bits, pair_records, coordinate_pair_records = separation_data(
        model, pairs, top_degree
    )
    top_indices = [
        index
        for index, coordinate in enumerate(model.coordinates)
        if coordinate.degree == top_degree
    ]
    tree_local_indices = [
        local_index
        for local_index, coordinate_index in enumerate(top_indices)
        if support_graph_data(
            model.arcs,
            model.coordinates[coordinate_index].representative,
            model.n,
        )["category"]
        == "TREE_ON_ALL_VERTICES"
    ]
    tree_union = 0
    for local_index in tree_local_indices:
        tree_union |= cover_bits[local_index]
    tree_separable_count = tree_union.bit_count()
    tree_blind_pair_indices = [
        pair_index for pair_index in range(len(pairs)) if not (tree_union >> pair_index) & 1
    ]

    extension_minimum, extension_solutions = covering_subsets(
        cover_bits, len(pairs)
    )
    external_maps = induced_external_maps(model, top_indices)
    extension_orbits = solution_external_orbits(extension_solutions, external_maps)

    tree_minimum, tree_solutions = covering_subsets(
        cover_bits, len(pairs), tree_local_indices
    )

    crosswalk_records: list[dict[str, object]] = []
    index_two_split_pair_indices: list[int] = []
    a_to_s: dict[int, int] = {}
    if model.group_name.startswith("A"):
        if companion is None or not companion.group_name.startswith("S"):
            raise ValueError("alternating model requires symmetric companion")
        a_to_s, crosswalk_records = sn_crosswalk(model, companion)
        index_two_split_pair_indices = [
            pair_index
            for pair_index, (left, right) in enumerate(pairs)
            if a_to_s[left] == a_to_s[right]
        ]

    shape_census: dict[str, int] = defaultdict(int)
    solution_records: list[dict[str, object]] = []
    for solution in extension_solutions:
        categories = sorted(
            support_graph_data(
                model.arcs,
                model.coordinates[top_indices[local_index]].representative,
                model.n,
            )["category"]
            for local_index in solution
        )
        shape_key = "+".join(categories)
        shape_census[shape_key] += 1
        solution_records.append(
            {
                "coordinate_ids": [
                    model.coordinate_id(model.coordinates[top_indices[index]])
                    for index in solution
                ],
                "support_categories": categories,
            }
        )

    for pair_index, record in enumerate(pair_records):
        record["index_two_split_pair"] = pair_index in set(index_two_split_pair_indices)
        record["tree_blind"] = pair_index in set(tree_blind_pair_indices)
        if model.group_name.startswith("A"):
            left, right = pairs[pair_index]
            record["S_parent_orbit_ids"] = [
                companion.pattern_id(
                    companion.pattern_representatives[a_to_s[left]]
                ),
                companion.pattern_id(
                    companion.pattern_representatives[a_to_s[right]]
                ),
            ]

    degree_profile = [
        sum(coordinate.degree == degree for coordinate in model.coordinates)
        for degree in range(1, top_degree + 1)
    ]
    return {
        "group": model.group_name,
        "n": model.n,
        "arc_count": len(model.arcs),
        "arc_order": [list(arc) for arc in model.arcs],
        "group_order": len(model.permutations),
        "pattern_orbit_count": len(model.pattern_representatives),
        "pattern_orbit_ids": [
            model.pattern_id(mask) for mask in model.pattern_representatives
        ],
        "coordinate_profile_degrees_1_to_top": degree_profile,
        "coordinate_metadata": coordinate_metadata(model),
        "residual_degree": residual_degree,
        "residual_pair_count": len(pairs),
        "residual_pairs": pair_records,
        "top_degree_pair_by_coordinate_separation_bitsets": coordinate_pair_records,
        "top_degree_tree_coordinate_count": len(tree_local_indices),
        "pairs_with_a_tree_separator": tree_separable_count,
        "tree_blind_pair_indices": tree_blind_pair_indices,
        "tree_blind_pair_count": len(tree_blind_pair_indices),
        "index_two_split_pair_indices": index_two_split_pair_indices,
        "index_two_split_pair_count": len(index_two_split_pair_indices),
        "all_tree_blind_pairs_are_index_two_split_pairs": all(
            pair_index in set(index_two_split_pair_indices)
            for pair_index in tree_blind_pair_indices
        ),
        "Sn_to_An_split_crosswalk": crosswalk_records,
        "conditional_top_degree_extension": {
            "minimum": extension_minimum,
            "solution_count_before_external_quotient": len(extension_solutions),
            "solutions": solution_records,
            "external_generator_coordinate_maps": [list(m) for m in external_maps],
            "external_orbit_count": len(extension_orbits),
            "external_orbits_as_solution_indices": [
                [extension_solutions.index(solution) for solution in orbit]
                for orbit in extension_orbits
            ],
            "support_shape_census": dict(sorted(shape_census.items())),
        },
        "tree_only_cover": {
            "minimum": tree_minimum,
            "solution_count": len(tree_solutions),
            "solutions": [
                [
                    model.coordinate_id(model.coordinates[top_indices[index]])
                    for index in solution
                ]
                for solution in tree_solutions
            ],
        },
    }


def target_comparisons(payloads: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    targets = {
        "S4": {
            "residual_pair_count": 39,
            "pairs_with_a_tree_separator": 39,
        },
        "A4": {
            "residual_pair_count": 51,
            "index_two_split_pair_count": 9,
            "pairs_with_a_tree_separator": 51,
        },
        "S5": {
            "pattern_orbit_count": 9608,
            "coordinate_profile_degrees_1_to_top": [1, 5, 16, 61],
            "residual_pair_count": 190,
            "pairs_with_a_tree_separator": 190,
            "top_degree_tree_coordinate_count": 27,
            "tree_only_cover.minimum": 5,
            "tree_only_cover.solution_count": 88,
            "conditional_top_degree_extension.minimum": 4,
            "conditional_top_degree_extension.solution_count_before_external_quotient": 2,
            "conditional_top_degree_extension.external_orbit_count": 1,
        },
        "A5": {
            "pattern_orbit_count": 17824,
            "coordinate_profile_degrees_1_to_top": [1, 6, 21, 96],
            "residual_pair_count": 113,
            "index_two_split_pair_count": 54,
            "tree_blind_pair_count": 8,
            "all_tree_blind_pairs_are_index_two_split_pairs": True,
            "conditional_top_degree_extension.minimum": 4,
            "conditional_top_degree_extension.solution_count_before_external_quotient": 200,
            "conditional_top_degree_extension.external_orbit_count": 50,
        },
    }

    def lookup(value: object, dotted: str) -> object:
        current = value
        for component in dotted.split("."):
            if not isinstance(current, dict):
                raise KeyError(dotted)
            current = current[component]
        return current

    comparisons: list[dict[str, object]] = []
    for group, expected_fields in targets.items():
        for field, expected in expected_fields.items():
            observed = lookup(payloads[group], field)
            comparisons.append(
                {
                    "group": group,
                    "field": field,
                    "expected": expected,
                    "observed": observed,
                    "pass": observed == expected,
                }
            )
    return comparisons


def resolve_project_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    return Path(__file__).resolve().parents[3]


def run(project_root: Path, output_dir: Path) -> int:
    start = time.perf_counter()
    specification = project_root / "schemas" / "five_vertex_specification.json"
    normalization = project_root / "docs" / "NORMALIZATION_LOCK.md"
    spec = json.loads(specification.read_text(encoding="utf-8"))
    if spec.get("specification_id") != EXPERIMENT_ID:
        raise ValueError("wrong five-vertex specification identity")
    normalization_text = normalization.read_text(encoding="utf-8")
    for required in ("g.(i,j) = (g(i),g(j))", "Squarefree orbit-sum coordinates"):
        if required not in normalization_text:
            raise ValueError(f"normalization missing marker: {required}")

    models: dict[str, Model] = {}
    for n in (4, 5):
        models[f"S{n}"] = build_model(n, False, n - 1)
        models[f"A{n}"] = build_model(n, True, n - 1)

    group_payloads = {
        "S4": model_payload(models["S4"], None),
        "A4": model_payload(models["A4"], models["S4"]),
        "S5": model_payload(models["S5"], None),
        "A5": model_payload(models["A5"], models["S5"]),
    }
    comparisons = target_comparisons(group_payloads)
    verdict = (
        "PASS_FIVE_VERTEX_CANONICAL_TARGETS"
        if all(row["pass"] for row in comparisons)
        else "FAIL_FIVE_VERTEX_SCIENTIFIC_DISAGREEMENT"
    )
    scientific_payload = {
        "schema": SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "phase": "CANONICAL_PAYLOAD",
        "scope": {"n_values": [4, 5], "n_greater_than_5_executed": False},
        "serialization": spec["canonical_serialization"],
        "groups": group_payloads,
        "target_comparisons": comparisons,
        "verdict": verdict,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    payload_path = output_dir / "canonical_payload.json"
    write_canonical_json(payload_path, scientific_payload)

    elapsed = round(time.perf_counter() - start, 6)
    print(
        f"ORBIT_SUM_PAYLOAD_{verdict}|groups=4|comparisons={len(comparisons)}|"
        f"payload_sha256={sha256_path(payload_path)}|seconds={elapsed}"
    )
    return 0 if verdict.startswith("PASS") else 2


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root")
    parser.add_argument("--output")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    project_root = resolve_project_root(arguments.project_root)
    output_dir = (
        Path(arguments.output).resolve()
        if arguments.output
        else project_root / "tmp" / "five_vertex_producer"
    )
    return run(project_root, output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
