#!/usr/bin/env python3
"""Primary family-degree probe using generator closure and orbit BFS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import defaultdict, deque
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    ROOT / "docs" / "NORMALIZATION_LOCK.md",
    ROOT / "schemas" / "family_degree_contract_v1.json",
    ROOT / "schemas" / "family_degree_specification.yaml",
)


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


def commit_lines(lines: list[str]) -> str:
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def compose(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(left[right[index]] for index in range(len(left)))


def vertex_generators(n: int, alternating: bool) -> list[tuple[int, ...]]:
    generators: list[tuple[int, ...]] = []
    if alternating:
        for third in range(2, n):
            value = list(range(n))
            value[0], value[1], value[third] = 1, third, 0
            generators.append(tuple(value))
    else:
        for index in range(n - 1):
            value = list(range(n))
            value[index], value[index + 1] = value[index + 1], value[index]
            generators.append(tuple(value))
    return generators


def group_closure(n: int, generators: list[tuple[int, ...]]) -> tuple[tuple[int, ...], ...]:
    identity = tuple(range(n))
    seen = {identity}
    queue = deque([identity])
    while queue:
        current = queue.popleft()
        for generator in generators:
            value = compose(current, generator)
            if value not in seen:
                seen.add(value)
                queue.append(value)
    return tuple(sorted(seen))


def carrier(n: int) -> tuple[tuple[int, int], ...]:
    return tuple((left, right) for left in range(n) for right in range(n) if left != right)


def induced_map(
    arcs: tuple[tuple[int, int], ...], permutation: tuple[int, ...]
) -> tuple[int, ...]:
    positions = {arc: index for index, arc in enumerate(arcs)}
    return tuple(positions[(permutation[left], permutation[right])] for left, right in arcs)


def transform(mask: int, mapping: tuple[int, ...]) -> int:
    value = 0
    remaining = mask
    while remaining:
        bit = remaining & -remaining
        index = bit.bit_length() - 1
        value |= 1 << mapping[index]
        remaining ^= bit
    return value


def bfs_orbit(seed: int, maps: tuple[tuple[int, ...], ...], visited: bytearray | set[int]) -> tuple[int, ...]:
    queue = deque([seed])
    members = [seed]
    if isinstance(visited, bytearray):
        visited[seed] = 1
    else:
        visited.add(seed)
    while queue:
        current = queue.popleft()
        for mapping in maps:
            value = transform(current, mapping)
            known = bool(visited[value]) if isinstance(visited, bytearray) else value in visited
            if not known:
                if isinstance(visited, bytearray):
                    visited[value] = 1
                else:
                    visited.add(value)
                queue.append(value)
                members.append(value)
    return tuple(sorted(members))


def subset_masks(size: int, degree: int) -> list[int]:
    return sorted(sum(1 << index for index in indices) for indices in combinations(range(size), degree))


def collision_summary(
    group: str, degree: int, rows: list[dict[str, object]], signature_key: str
) -> dict[str, object]:
    fibres: dict[tuple[int, ...], list[int]] = defaultdict(list)
    for row in rows:
        fibres[tuple(row[signature_key])].append(int(row["canonical_mask"]))
    nontrivial = [(signature, sorted(masks)) for signature, masks in fibres.items() if len(masks) > 1]
    nontrivial.sort(key=lambda item: (item[0], item[1]))
    pairs = sum(len(masks) * (len(masks) - 1) // 2 for _, masks in nontrivial)
    classes = sum(len(masks) for _, masks in nontrivial)
    first = min((masks[0], masks[1]) for _, masks in nontrivial) if nontrivial else None
    lines = [
        f"{group}|{degree}|{','.join(map(str, signature))}|{','.join(map(str, masks))}"
        for signature, masks in nontrivial
    ]
    return {
        "colliding_class_count": classes,
        "colliding_pair_count": pairs,
        "collision_fibre_count": len(nontrivial),
        "collision_fibre_sha256": commit_lines(lines),
        "degree": degree,
        "distinct_signature_count": len(fibres),
        "first_collision_masks": list(first) if first is not None else None,
        "max_fibre_size": max((len(masks) for _, masks in nontrivial), default=1),
    }


def build_group(n: int, alternating: bool) -> dict[str, object]:
    group = f"{'A' if alternating else 'S'}{n}"
    arcs = carrier(n)
    generators = vertex_generators(n, alternating)
    vertices = group_closure(n, generators)
    factorial = 1
    for value in range(2, n + 1):
        factorial *= value
    expected_order = factorial // (2 if alternating else 1)
    if len(vertices) != expected_order:
        raise ValueError(f"{group} generator closure order {len(vertices)} != {expected_order}")
    generator_maps = tuple(induced_map(arcs, value) for value in generators)

    coordinate_rows: list[dict[str, object]] = []
    support_to_index: dict[int, int] = {}
    degree_counts: dict[str, int] = {}
    for degree in (1, 2, 3):
        visited_supports: set[int] = set()
        degree_rows: list[dict[str, object]] = []
        for seed in subset_masks(len(arcs), degree):
            if seed in visited_supports:
                continue
            orbit = bfs_orbit(seed, generator_maps, visited_supports)
            if orbit[0] != seed:
                raise ValueError(f"{group} noncanonical coordinate seed")
            if len(vertices) % len(orbit):
                raise ValueError(f"{group} coordinate orbit-stabilizer failure")
            degree_rows.append(
                {
                    "canonical_support_mask": seed,
                    "degree": degree,
                    "orbit_masks": orbit,
                    "orbit_size": len(orbit),
                    "setwise_stabilizer_order": len(vertices) // len(orbit),
                }
            )
        degree_rows.sort(key=lambda row: int(row["canonical_support_mask"]))
        for degree_index, row in enumerate(degree_rows):
            row["degree_index"] = degree_index
            global_index = len(coordinate_rows)
            coordinate_rows.append(row)
            for support in row["orbit_masks"]:
                if int(support) in support_to_index:
                    raise ValueError(f"{group} coordinate partition overlap")
                support_to_index[int(support)] = global_index
        degree_counts[str(degree)] = len(degree_rows)
    if len(support_to_index) != sum(
        len(subset_masks(len(arcs), degree)) for degree in (1, 2, 3)
    ):
        raise ValueError(f"{group} incomplete coordinate partition")

    offsets = {
        1: degree_counts["1"],
        2: degree_counts["1"] + degree_counts["2"],
        3: len(coordinate_rows),
    }
    visited_patterns = bytearray(1 << len(arcs))
    pattern_rows: list[dict[str, object]] = []
    for seed in range(1 << len(arcs)):
        if visited_patterns[seed]:
            continue
        orbit = bfs_orbit(seed, generator_maps, visited_patterns)
        if orbit[0] != seed:
            raise ValueError(f"{group} noncanonical pattern seed")
        if len(vertices) % len(orbit):
            raise ValueError(f"{group} pattern orbit-stabilizer failure")
        counts = [0] * len(coordinate_rows)
        selected = [index for index in range(len(arcs)) if seed & (1 << index)]
        for degree in (1, 2, 3):
            for indices in combinations(selected, degree):
                support = sum(1 << index for index in indices)
                counts[support_to_index[support]] += 1
        pattern_rows.append(
            {
                "canonical_mask": seed,
                "orbit_size": len(orbit),
                "setwise_stabilizer_order": len(vertices) // len(orbit),
                "signature_through_1": tuple(counts[: offsets[1]]),
                "signature_through_2": tuple(counts[: offsets[2]]),
                "signature_through_3": tuple(counts),
            }
        )
    if sum(int(row["orbit_size"]) for row in pattern_rows) != 1 << len(arcs):
        raise ValueError(f"{group} incomplete pattern partition")

    coordinate_lines = [
        "|".join(
            map(
                str,
                (
                    group,
                    row["degree"],
                    row["degree_index"],
                    row["canonical_support_mask"],
                    row["orbit_size"],
                    row["setwise_stabilizer_order"],
                ),
            )
        )
        for row in coordinate_rows
    ]
    pattern_lines = [
        "|".join(
            (
                group,
                str(row["canonical_mask"]),
                str(row["orbit_size"]),
                str(row["setwise_stabilizer_order"]),
                ",".join(map(str, row["signature_through_1"])),
                ",".join(map(str, row["signature_through_2"])),
                ",".join(map(str, row["signature_through_3"])),
            )
        )
        for row in pattern_rows
    ]
    summaries = [
        collision_summary(group, degree, pattern_rows, f"signature_through_{degree}")
        for degree in (1, 2, 3)
    ]
    reconstruction: int | str = "GT3"
    for summary in summaries:
        if int(summary["collision_fibre_count"]) == 0:
            reconstruction = int(summary["degree"])
            break
    return {
        "carrier_size": len(arcs),
        "coordinate_counts": degree_counts,
        "coordinate_registry_sha256": commit_lines(coordinate_lines),
        "degree_summaries": summaries,
        "group": group,
        "group_order": len(vertices),
        "n": n,
        "pattern_orbit_count": len(pattern_rows),
        "pattern_registry_sha256": commit_lines(pattern_lines),
        "pattern_space_size": 1 << len(arcs),
        "reconstruction_degree_within_panel": reconstruction,
        "total_coordinate_count": len(coordinate_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "certificates" / "family_degree" / "primary",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    input_hashes = verify_inputs()
    groups = [build_group(n, alternating) for n in (3, 4, 5) for alternating in (False, True)]
    artifact = {
        "claim_ceiling": "finite_panel_only_no_universal_inference",
        "experiment_id": "FAMILY_DEGREE",
        "groups": groups,
        "normalization": {
            "arc_order": "lexicographic_i_then_j_excluding_loops",
            "carrier": "all_directed_nonloop_arcs",
            "coordinate_family": "cumulative_squarefree_orbit_sums_degrees_1_2_3",
            "equivalence": "declared_vertex_group_only",
            "group_labels": ["S3", "A3", "S4", "A4", "S5", "A5"],
            "vertex_parity": "inversion_parity",
        },
        "schema_version": "family_degree_family_probe_v1",
    }
    artifact_path = args.output / "family_probe.json"
    write_new_json(artifact_path, artifact)
    build_summary = {
        "artifact_hashes": {"family_probe.json": sha256(artifact_path)},
        "experiment_id": "FAMILY_DEGREE",
        "implementation": "vertex_generator_closure_plus_orbit_breadth_first_search",
        "independence_declaration": {
            "consumed_other_implementation": False,
            "shared_scientific_code": [],
        },
        "input_hashes": input_hashes,
        "random_seed": None,
        "implementation_id": "PRIMARY_FAMILY_ENUMERATION",
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "schema_version": "family_degree_build_summary_v1",
        "summary": {
            row["group"]: {
                "degree": row["reconstruction_degree_within_panel"],
                "pattern_orbits": row["pattern_orbit_count"],
            }
            for row in groups
        },
        "verdict": "PASS",
    }
    write_new_json(args.output / "build_summary.json", build_summary)
    summary = ",".join(
        f"{row['group']}={row['pattern_orbit_count']}/d{row['reconstruction_degree_within_panel']}"
        for row in groups
    )
    print(f"FAMILY_DEGREE_PRIMARY_PASS|{summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
