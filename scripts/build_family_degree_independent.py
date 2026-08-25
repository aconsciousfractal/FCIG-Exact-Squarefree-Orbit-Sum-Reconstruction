#!/usr/bin/env python3
"""Independent family-degree probe using full permutation enumeration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import defaultdict
from itertools import combinations, permutations
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


def inversion_parity(value: tuple[int, ...]) -> int:
    return sum(value[left] > value[right] for left in range(len(value)) for right in range(left + 1, len(value))) % 2


def vertex_group(n: int, alternating: bool) -> tuple[tuple[int, ...], ...]:
    values = tuple(
        value
        for value in permutations(range(n))
        if not alternating or inversion_parity(value) == 0
    )
    expected = 1
    for factor in range(2, n + 1):
        expected *= factor
    if alternating:
        expected //= 2
    if len(values) != expected:
        raise ValueError(f"permutation enumeration order {len(values)} != {expected}")
    return values


def carrier(n: int) -> tuple[tuple[int, int], ...]:
    return tuple((left, right) for left in range(n) for right in range(n) if left != right)


def induced_maps(
    arcs: tuple[tuple[int, int], ...], group: tuple[tuple[int, ...], ...]
) -> tuple[tuple[int, ...], ...]:
    positions = {arc: index for index, arc in enumerate(arcs)}
    return tuple(
        tuple(positions[(permutation[left], permutation[right])] for left, right in arcs)
        for permutation in group
    )


def transform(mask: int, mapping: tuple[int, ...]) -> int:
    output = 0
    bit_index = 0
    value = mask
    while value:
        if value & 1:
            output |= 1 << mapping[bit_index]
        value >>= 1
        bit_index += 1
    return output


def direct_orbit(seed: int, maps: tuple[tuple[int, ...], ...]) -> tuple[int, ...]:
    return tuple(sorted({transform(seed, mapping) for mapping in maps}))


def subset_masks(size: int, degree: int) -> list[int]:
    values: list[int] = []
    for indices in combinations(range(size), degree):
        mask = 0
        for index in indices:
            mask |= 1 << index
        values.append(mask)
    values.sort()
    return values


def collision_summary(
    group: str, degree: int, rows: list[dict[str, object]], signature_key: str
) -> dict[str, object]:
    fibres: dict[tuple[int, ...], list[int]] = defaultdict(list)
    for row in rows:
        fibres[tuple(row[signature_key])].append(int(row["canonical_mask"]))
    nontrivial = sorted(
        (signature, sorted(masks))
        for signature, masks in fibres.items()
        if len(masks) > 1
    )
    collision_pairs = sum(len(masks) * (len(masks) - 1) // 2 for _, masks in nontrivial)
    first = min((masks[0], masks[1]) for _, masks in nontrivial) if nontrivial else None
    lines = [
        f"{group}|{degree}|{','.join(str(value) for value in signature)}|{','.join(str(value) for value in masks)}"
        for signature, masks in nontrivial
    ]
    return {
        "colliding_class_count": sum(len(masks) for _, masks in nontrivial),
        "colliding_pair_count": collision_pairs,
        "collision_fibre_count": len(nontrivial),
        "collision_fibre_sha256": commit_lines(lines),
        "degree": degree,
        "distinct_signature_count": len(fibres),
        "first_collision_masks": list(first) if first is not None else None,
        "max_fibre_size": max((len(masks) for _, masks in nontrivial), default=1),
    }


def build_group(n: int, alternating: bool) -> dict[str, object]:
    label = f"{'A' if alternating else 'S'}{n}"
    arcs = carrier(n)
    vertices = vertex_group(n, alternating)
    maps = induced_maps(arcs, vertices)

    coordinate_rows: list[dict[str, object]] = []
    degree_counts: dict[str, int] = {}
    for degree in (1, 2, 3):
        unseen = set(subset_masks(len(arcs), degree))
        degree_rows: list[dict[str, object]] = []
        while unseen:
            seed = min(unseen)
            orbit = direct_orbit(seed, maps)
            if orbit[0] != seed or not set(orbit).issubset(unseen):
                raise ValueError(f"{label} coordinate orbit partition failure")
            unseen.difference_update(orbit)
            if len(vertices) % len(orbit):
                raise ValueError(f"{label} coordinate orbit-stabilizer failure")
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
            coordinate_rows.append(row)
        degree_counts[str(degree)] = len(degree_rows)

    offsets = {
        1: degree_counts["1"],
        2: degree_counts["1"] + degree_counts["2"],
        3: len(coordinate_rows),
    }
    visited = bytearray(1 << len(arcs))
    pattern_rows: list[dict[str, object]] = []
    for seed in range(1 << len(arcs)):
        if visited[seed]:
            continue
        orbit = direct_orbit(seed, maps)
        if orbit[0] != seed:
            raise ValueError(f"{label} noncanonical pattern seed")
        if any(visited[value] for value in orbit):
            raise ValueError(f"{label} pattern orbit overlap")
        for value in orbit:
            visited[value] = 1
        if len(vertices) % len(orbit):
            raise ValueError(f"{label} pattern orbit-stabilizer failure")
        counts = [
            sum(1 for support in row["orbit_masks"] if int(support) & seed == int(support))
            for row in coordinate_rows
        ]
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
    if not all(visited):
        raise ValueError(f"{label} incomplete pattern partition")
    if sum(int(row["orbit_size"]) for row in pattern_rows) != 1 << len(arcs):
        raise ValueError(f"{label} pattern orbit-size sum failure")

    coordinate_lines = [
        f"{label}|{row['degree']}|{row['degree_index']}|{row['canonical_support_mask']}|{row['orbit_size']}|{row['setwise_stabilizer_order']}"
        for row in coordinate_rows
    ]
    pattern_lines = [
        "|".join(
            (
                label,
                str(row["canonical_mask"]),
                str(row["orbit_size"]),
                str(row["setwise_stabilizer_order"]),
                ",".join(str(value) for value in row["signature_through_1"]),
                ",".join(str(value) for value in row["signature_through_2"]),
                ",".join(str(value) for value in row["signature_through_3"]),
            )
        )
        for row in pattern_rows
    ]
    summaries = [
        collision_summary(label, degree, pattern_rows, f"signature_through_{degree}")
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
        "group": label,
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
        default=ROOT / "certificates" / "family_degree" / "independent",
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
        "implementation": "full_vertex_permutation_enumeration_plus_direct_orbit_images",
        "independence_declaration": {
            "consumed_other_implementation": False,
            "shared_scientific_code": [],
        },
        "input_hashes": input_hashes,
        "random_seed": None,
        "implementation_id": "INDEPENDENT_FAMILY_ENUMERATION",
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
    print(f"FAMILY_DEGREE_INDEPENDENT_PASS|{summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
