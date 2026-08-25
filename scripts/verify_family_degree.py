#!/usr/bin/env python3
"""Independent checker for the family-degree and structural certificates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import defaultdict
from copy import deepcopy
from itertools import combinations, permutations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "certificates" / "family_degree"
MINIMUM = ROOT / "certificates" / "minimum_fingerprints"
ORBIT_ATLAS = ROOT / "certificates" / "orbit_atlas"
INPUTS = (
    ROOT / "docs" / "NORMALIZATION_LOCK.md",
    ROOT / "schemas" / "family_degree_contract_v1.json",
    ROOT / "schemas" / "family_degree_specification.yaml",
)
DECLARED_CUBIC = {"S4": (11, 16), "A4": (22, 23, 24, 29)}
GROUP_LABELS = ["S3", "A3", "S4", "A4", "S5", "A5"]


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
    data = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def read_json(path: Path) -> dict[str, object]:
    with open(native(path), "r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


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


def parity(value: tuple[int, ...]) -> int:
    inversions = 0
    for left in range(len(value)):
        for right in range(left + 1, len(value)):
            inversions += value[left] > value[right]
    return inversions & 1


def carrier(n: int) -> tuple[tuple[int, int], ...]:
    return tuple((i, j) for i in range(n) for j in range(n) if i != j)


def vertex_group(n: int, alternating: bool) -> tuple[tuple[int, ...], ...]:
    group = tuple(
        value for value in permutations(range(n)) if not alternating or parity(value) == 0
    )
    factorial = 1
    for value in range(2, n + 1):
        factorial *= value
    expected = factorial // (2 if alternating else 1)
    if len(group) != expected:
        raise ValueError("independent group rebuild failure")
    return group


def arc_maps(
    arcs: tuple[tuple[int, int], ...], group: tuple[tuple[int, ...], ...]
) -> tuple[tuple[int, ...], ...]:
    lookup = {arc: index for index, arc in enumerate(arcs)}
    return tuple(
        tuple(lookup[(value[i], value[j])] for i, j in arcs)
        for value in group
    )


def act(mask: int, mapping: tuple[int, ...]) -> int:
    result = 0
    for index in range(len(mapping)):
        if mask & (1 << index):
            result |= 1 << mapping[index]
    return result


def cycle_count(mapping: tuple[int, ...]) -> int:
    seen: set[int] = set()
    cycles = 0
    for seed in range(len(mapping)):
        if seed in seen:
            continue
        cycles += 1
        current = seed
        while current not in seen:
            seen.add(current)
            current = mapping[current]
    return cycles


def masks_of_weight(size: int, weight: int) -> list[int]:
    return sorted(sum(1 << index for index in row) for row in combinations(range(size), weight))


def nontrivial_fibres(
    rows: list[dict[str, object]], signature_key: str
) -> list[tuple[tuple[int, ...], list[int]]]:
    fibres: dict[tuple[int, ...], list[int]] = defaultdict(list)
    for row in rows:
        fibres[tuple(row[signature_key])].append(int(row["canonical_mask"]))
    return sorted(
        (signature, sorted(masks))
        for signature, masks in fibres.items()
        if len(masks) > 1
    )


def rebuild_group(n: int, alternating: bool) -> tuple[dict[str, object], dict[str, object]]:
    label = f"{'A' if alternating else 'S'}{n}"
    arcs = carrier(n)
    group = vertex_group(n, alternating)
    maps = arc_maps(arcs, group)

    coordinate_rows: list[dict[str, object]] = []
    support_to_coordinate: dict[int, int] = {}
    counts: dict[str, int] = {}
    for degree in (1, 2, 3):
        remaining = set(masks_of_weight(len(arcs), degree))
        rows: list[dict[str, object]] = []
        while remaining:
            seed = min(remaining)
            orbit = tuple(sorted({act(seed, mapping) for mapping in maps}))
            if orbit[0] != seed or not set(orbit).issubset(remaining):
                raise ValueError(f"{label} independent coordinate partition failure")
            remaining.difference_update(orbit)
            rows.append(
                {
                    "canonical_support_mask": seed,
                    "degree": degree,
                    "orbit_masks": orbit,
                    "orbit_size": len(orbit),
                    "setwise_stabilizer_order": len(group) // len(orbit),
                }
            )
        rows.sort(key=lambda row: int(row["canonical_support_mask"]))
        for degree_index, row in enumerate(rows):
            row["degree_index"] = degree_index
            coordinate_index = len(coordinate_rows)
            coordinate_rows.append(row)
            for support in row["orbit_masks"]:
                if int(support) in support_to_coordinate:
                    raise ValueError(f"{label} independent coordinate overlap")
                support_to_coordinate[int(support)] = coordinate_index
        counts[str(degree)] = len(rows)

    offsets = {
        1: counts["1"],
        2: counts["1"] + counts["2"],
        3: len(coordinate_rows),
    }
    seen: set[int] = set()
    pattern_rows: list[dict[str, object]] = []
    for seed in range(1 << len(arcs)):
        if seed in seen:
            continue
        orbit = tuple(sorted({act(seed, mapping) for mapping in maps}))
        if orbit[0] != seed or set(orbit) & seen:
            raise ValueError(f"{label} independent pattern partition failure")
        seen.update(orbit)
        signature = [0] * len(coordinate_rows)
        selected = [index for index in range(len(arcs)) if seed & (1 << index)]
        for degree in (1, 2, 3):
            for chosen in combinations(selected, degree):
                support = sum(1 << index for index in chosen)
                signature[support_to_coordinate[support]] += 1
        pattern_rows.append(
            {
                "canonical_mask": seed,
                "orbit_size": len(orbit),
                "setwise_stabilizer_order": len(group) // len(orbit),
                "signature_through_1": tuple(signature[: offsets[1]]),
                "signature_through_2": tuple(signature[: offsets[2]]),
                "signature_through_3": tuple(signature),
            }
        )
    if len(seen) != 1 << len(arcs):
        raise ValueError(f"{label} independent pattern coverage failure")
    burnside = sum(1 << cycle_count(mapping) for mapping in maps) // len(group)
    if burnside != len(pattern_rows):
        raise ValueError(f"{label} Burnside crosscheck failure")

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
                ",".join(map(str, row["signature_through_1"])),
                ",".join(map(str, row["signature_through_2"])),
                ",".join(map(str, row["signature_through_3"])),
            )
        )
        for row in pattern_rows
    ]
    degree_summaries: list[dict[str, object]] = []
    for degree in (1, 2, 3):
        key = f"signature_through_{degree}"
        all_fibres: dict[tuple[int, ...], int] = defaultdict(int)
        for row in pattern_rows:
            all_fibres[tuple(row[key])] += 1
        fibres = nontrivial_fibres(pattern_rows, key)
        lines = [
            f"{label}|{degree}|{','.join(map(str, signature))}|{','.join(map(str, masks))}"
            for signature, masks in fibres
        ]
        first = min((masks[0], masks[1]) for _, masks in fibres) if fibres else None
        degree_summaries.append(
            {
                "colliding_class_count": sum(len(masks) for _, masks in fibres),
                "colliding_pair_count": sum(len(masks) * (len(masks) - 1) // 2 for _, masks in fibres),
                "collision_fibre_count": len(fibres),
                "collision_fibre_sha256": commit_lines(lines),
                "degree": degree,
                "distinct_signature_count": len(all_fibres),
                "first_collision_masks": list(first) if first is not None else None,
                "max_fibre_size": max((len(masks) for _, masks in fibres), default=1),
            }
        )
    reconstruction: int | str = "GT3"
    for row in degree_summaries:
        if int(row["collision_fibre_count"]) == 0:
            reconstruction = int(row["degree"])
            break
    scientific = {
        "carrier_size": len(arcs),
        "coordinate_counts": counts,
        "coordinate_registry_sha256": commit_lines(coordinate_lines),
        "degree_summaries": degree_summaries,
        "group": label,
        "group_order": len(group),
        "n": n,
        "pattern_orbit_count": len(pattern_rows),
        "pattern_registry_sha256": commit_lines(pattern_lines),
        "pattern_space_size": 1 << len(arcs),
        "reconstruction_degree_within_panel": reconstruction,
        "total_coordinate_count": len(coordinate_rows),
    }
    detail = {
        "burnside_pattern_orbit_count": burnside,
        "coordinate_rows": coordinate_rows,
        "pattern_rows": pattern_rows,
    }
    return scientific, detail


def rebuild_family() -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    groups: list[dict[str, object]] = []
    details: dict[str, dict[str, object]] = {}
    for n in (3, 4, 5):
        for alternating in (False, True):
            scientific, detail = rebuild_group(n, alternating)
            groups.append(scientific)
            details[str(scientific["group"])] = detail
    document = {
        "claim_ceiling": "finite_panel_only_no_universal_inference",
        "experiment_id": "FAMILY_DEGREE",
        "groups": groups,
        "normalization": {
            "arc_order": "lexicographic_i_then_j_excluding_loops",
            "carrier": "all_directed_nonloop_arcs",
            "coordinate_family": "cumulative_squarefree_orbit_sums_degrees_1_2_3",
            "equivalence": "declared_vertex_group_only",
            "group_labels": GROUP_LABELS,
            "vertex_parity": "inversion_parity",
        },
        "schema_version": "family_degree_family_probe_v1",
    }
    return document, details


def validate_family_document(document: dict[str, object], expected: dict[str, object]) -> None:
    if document.get("claim_ceiling") != "finite_panel_only_no_universal_inference":
        raise ValueError("forbidden claim failure")
    normalization = document.get("normalization")
    if not isinstance(normalization, dict):
        raise ValueError("normalization block missing")
    if normalization.get("carrier") != "all_directed_nonloop_arcs":
        raise ValueError("carrier contract failure")
    if normalization.get("arc_order") != "lexicographic_i_then_j_excluding_loops":
        raise ValueError("arc order commitment failure")
    if normalization.get("vertex_parity") != "inversion_parity":
        raise ValueError("vertex parity contract failure")
    if normalization.get("equivalence") != "declared_vertex_group_only":
        raise ValueError("equivalence contract failure")
    if normalization.get("group_labels") != GROUP_LABELS:
        raise ValueError("exact panel membership failure")
    rows = document.get("groups")
    if not isinstance(rows, list) or [row.get("group") for row in rows] != GROUP_LABELS:
        raise ValueError("exact panel membership failure")
    expected_rows = {str(row["group"]): row for row in expected["groups"]}
    for row in rows:
        label = str(row["group"])
        target = expected_rows[label]
        if row.get("group_order") != target["group_order"]:
            raise ValueError(f"{label} independent group rebuild failure")
        if row.get("carrier_size") != target["carrier_size"]:
            raise ValueError(f"{label} carrier size mismatch")
        if row.get("pattern_orbit_count") != target["pattern_orbit_count"]:
            raise ValueError(f"{label} independent pattern partition failure")
        if row.get("coordinate_counts") != target["coordinate_counts"]:
            raise ValueError(f"{label} independent coordinate partition failure")
        if row.get("coordinate_registry_sha256") != target["coordinate_registry_sha256"]:
            raise ValueError(f"{label} coordinate registry commitment failure")
        if row.get("pattern_registry_sha256") != target["pattern_registry_sha256"]:
            raise ValueError(f"{label} normalized pattern commitment failure")
        summaries = row.get("degree_summaries")
        if not isinstance(summaries, list) or len(summaries) != 3:
            raise ValueError(f"{label} collision summary count failure")
        for observed, wanted in zip(summaries, target["degree_summaries"], strict=True):
            if observed.get("first_collision_masks") != wanted["first_collision_masks"]:
                raise ValueError(f"{label} canonical collision witness failure")
            if observed.get("collision_fibre_sha256") != wanted["collision_fibre_sha256"]:
                raise ValueError(f"{label} collision fibre commitment failure")
            if observed != wanted:
                raise ValueError(f"{label} collision statistics failure")
        if row != target:
            raise ValueError(f"{label} complete family row mismatch")
    if document != expected:
        raise ValueError("complete family artifact mismatch")


def validate_n4_crosswalk(
    details: dict[str, dict[str, object]],
    coordinate_registry: dict[str, object],
    pattern_registry: dict[str, object],
) -> str:
    coordinate_groups = {str(row["group"]): row for row in coordinate_registry["groups"]}
    pattern_groups = {str(row["group"]): row for row in pattern_registry["groups"]}
    lines: list[str] = []
    for label in ("S4", "A4"):
        expected_coordinates = details[label]["coordinate_rows"]
        observed_coordinates = coordinate_groups[label]["rows"]
        if len(expected_coordinates) != len(observed_coordinates):
            raise ValueError(f"{label} n4 ORBIT_ATLAS coordinate crosswalk failure")
        for expected, observed in zip(expected_coordinates, observed_coordinates, strict=True):
            coordinate_id = f"{label}-D{expected['degree']}-C{int(expected['degree_index']):03d}"
            fields = (
                observed.get("coordinate_id") == coordinate_id,
                observed.get("degree") == expected["degree"],
                observed.get("degree_index") == expected["degree_index"],
                observed.get("canonical_support_mask") == expected["canonical_support_mask"],
                observed.get("orbit_size") == expected["orbit_size"],
                observed.get("setwise_stabilizer_order") == expected["setwise_stabilizer_order"],
            )
            if not all(fields):
                raise ValueError(f"{label} n4 ORBIT_ATLAS coordinate crosswalk failure")
            lines.append(f"{label}|coordinate|{coordinate_id}|PASS")
        expected_patterns = details[label]["pattern_rows"]
        observed_patterns = pattern_groups[label]["rows"]
        if len(expected_patterns) != len(observed_patterns):
            raise ValueError(f"{label} n4 ORBIT_ATLAS pattern crosswalk failure")
        for index, (expected, observed) in enumerate(zip(expected_patterns, observed_patterns, strict=True)):
            fields = (
                observed.get("pattern_id") == f"{label}-P{index:03d}",
                observed.get("canonical_mask") == expected["canonical_mask"],
                observed.get("orbit_size") == expected["orbit_size"],
                observed.get("setwise_stabilizer_order") == expected["setwise_stabilizer_order"],
                tuple(observed.get("signature_through_1", [])) == expected["signature_through_1"],
                tuple(observed.get("signature_through_2", [])) == expected["signature_through_2"],
                tuple(observed.get("signature_through_3", [])) == expected["signature_through_3"],
            )
            if not all(fields):
                raise ValueError(f"{label} n4 ORBIT_ATLAS pattern crosswalk failure at row {index}")
        lines.append(f"{label}|patterns|{len(expected_patterns)}|PASS")
    return commit_lines(lines)


def compact_constraint(row: dict[str, object], index: int) -> dict[str, object]:
    return {
        "constraint_id": row["constraint_id"],
        "constraint_index": index,
        "coordinate_ids": row["coordinate_ids"],
        "left_pattern_id": row["left_pattern_id"],
        "mask_int": row["mask_int"],
        "right_pattern_id": row["right_pattern_id"],
        "witness_pair_id": row["witness_pair_id"],
    }


def validate_structural_document(
    certificate: dict[str, object], instance: dict[str, object], minimum: dict[str, object]
) -> None:
    if certificate.get("claim_ceiling") != "finite_four_vertex_dictionary_only":
        raise ValueError("structural forbidden claim failure")
    certificate_rows = certificate.get("groups")
    if not isinstance(certificate_rows, list) or [row.get("group") for row in certificate_rows] != ["S4", "A4"]:
        raise ValueError("structural group scope failure")
    instances = {str(row["group"]): row for row in instance["groups"]}
    minima = {str(row["group"]): row for row in minimum["groups"]}
    for observed in certificate_rows:
        label = str(observed["group"])
        source = instances[label]
        constraints = list(source["inclusion_minimal_constraints"])
        coordinate_ids = [str(value) for value in source["coordinate_ids"]]
        d1 = [value for value in coordinate_ids if "-D1-" in value]
        d2 = [value for value in coordinate_ids if "-D2-" in value]
        d3 = [value for value in coordinate_ids if "-D3-" in value]
        singleton_candidates = [
            (index, row)
            for index, row in enumerate(constraints)
            if list(row["coordinate_ids"]) == d1
        ]
        if len(singleton_candidates) != 1:
            raise ValueError(f"{label} source singleton ambiguity")
        singleton_index, singleton = singleton_candidates[0]
        if observed.get("forced_degree_one") != compact_constraint(singleton, singleton_index):
            raise ValueError(f"{label} forced singleton constraint failure")

        actual_edges: dict[tuple[str, str], tuple[int, dict[str, object]]] = {}
        for index, row in enumerate(constraints):
            values = tuple(sorted(str(value) for value in row["coordinate_ids"]))
            if len(values) == 2 and set(values).issubset(d2):
                actual_edges[values] = (index, row)
        expected_edge_keys = sorted(combinations(d2, 2))
        graph = observed.get("complete_quadratic_graph")
        if not isinstance(graph, dict):
            raise ValueError(f"{label} complete quadratic graph failure")
        expected_edges = [
            {
                **compact_constraint(actual_edges[edge][1], actual_edges[edge][0]),
                "edge": list(edge),
            }
            for edge in expected_edge_keys
        ]
        if graph.get("edges") != expected_edges or graph.get("edge_count") != len(expected_edges):
            raise ValueError(f"{label} complete quadratic graph failure")
        if graph.get("vertex_cover_lower_bound") != len(d2) - 1:
            raise ValueError(f"{label} complete graph vertex-cover failure")

        cubic = observed.get("disjoint_cubic_constraints")
        if not isinstance(cubic, dict) or not isinstance(cubic.get("blocks"), list):
            raise ValueError(f"{label} cubic block failure")
        blocks = cubic["blocks"]
        block_sets = [set(str(value) for value in row.get("coordinate_ids", [])) for row in blocks]
        if any(not values or not values.issubset(d3) for values in block_sets):
            raise ValueError(f"{label} cubic-only block failure")
        if any(left & right for left, right in combinations(block_sets, 2)):
            raise ValueError(f"{label} cubic disjointness failure")
        expected_blocks = [
            compact_constraint(constraints[index], index) for index in DECLARED_CUBIC[label]
        ]
        if blocks != expected_blocks:
            raise ValueError(f"{label} MINIMUM cubic constraint crosswalk failure")
        if cubic.get("packing_lower_bound") != len(expected_blocks):
            raise ValueError(f"{label} cubic packing arithmetic failure")

        feasible = observed.get("canonical_feasible_support")
        if not isinstance(feasible, dict) or not isinstance(feasible.get("coordinate_ids"), list):
            raise ValueError(f"{label} feasible support missing")
        support = [str(value) for value in feasible["coordinate_ids"]]
        try:
            support_mask = sum(1 << coordinate_ids.index(value) for value in support)
        except ValueError as error:
            raise ValueError(f"{label} feasible support unknown coordinate") from error
        missed = [
            row for row in source["distinct_separator_masks"] if support_mask & int(row["mask_int"]) == 0
        ]
        if missed:
            raise ValueError(f"{label} exhaustive separator coverage failure")
        if support != [str(value) for value in minima[label]["canonical_coordinate_ids"]]:
            raise ValueError(f"{label} canonical feasible support crosswalk failure")

        arithmetic = observed.get("lower_bound_arithmetic")
        lower = 1 + len(d2) - 1 + len(expected_blocks)
        if not isinstance(arithmetic, dict) or arithmetic.get("lower_bound") != lower:
            raise ValueError(f"{label} structural block sum failure")
        if arithmetic.get("claimed_minimum") != int(minima[label]["minimum_size"]):
            raise ValueError(f"{label} structural minimum crosswalk failure")
        if lower != int(minima[label]["minimum_size"]):
            raise ValueError(f"{label} structural equality failure")
        if set(d1) & set(d2) or set(d1) & set(d3) or set(d2) & set(d3):
            raise ValueError(f"{label} degree block disjointness failure")


def validate_bundle(root: Path) -> tuple[dict[str, object], dict[str, dict[str, object]], str]:
    verify_inputs()
    primary_path = root / "primary" / "family_probe.json"
    independent_path = root / "independent" / "family_probe.json"
    with open(native(primary_path), "rb") as stream:
        bytes_a = stream.read()
    with open(native(independent_path), "rb") as stream:
        bytes_b = stream.read()
    if bytes_a != bytes_b:
        raise ValueError("family implementation byte disagreement")
    family_document = json.loads(bytes_a.decode("utf-8"))
    expected, details = rebuild_family()
    validate_family_document(family_document, expected)
    if bytes_a != canonical_bytes(expected):
        raise ValueError("family artifact canonical serialization mismatch")
    coordinate_registry = read_json(ORBIT_ATLAS / "primary" / "coordinate_registry.json")
    pattern_registry = read_json(ORBIT_ATLAS / "primary" / "pattern_registry.json")
    crosswalk_sha = validate_n4_crosswalk(details, coordinate_registry, pattern_registry)
    certificate = read_json(root / "structural" / "finite_theorem_certificate.json")
    instance = read_json(MINIMUM / "primary" / "instance.json")
    minimum = read_json(MINIMUM / "primary" / "minimum_fingerprints.json")
    validate_structural_document(certificate, instance, minimum)
    return expected, details, crosswalk_sha


def verification_summary(root: Path, family: dict[str, object], crosswalk_sha: str) -> dict[str, object]:
    return {
        "byte_identical_family_artifact": True,
        "commitment_agreement": True,
        "experiment_id": "FAMILY_DEGREE",
        "family_artifact_sha256": sha256(root / "primary" / "family_probe.json"),
        "independent_rebuild": "PASS",
        "n4_orbit_atlas_crosswalk": "PASS",
        "n4_orbit_atlas_crosswalk_sha256": crosswalk_sha,
        "schema_version": "family_degree_verification_summary_v1",
        "structural_theorem": "PASS_S4_7_A4_11",
        "summary": {
            row["group"]: {
                "coordinate_counts": row["coordinate_counts"],
                "degree": row["reconstruction_degree_within_panel"],
                "degree_three_colliding_pairs": row["degree_summaries"][2]["colliding_pair_count"],
                "pattern_orbits": row["pattern_orbit_count"],
            }
            for row in family["groups"]
        },
        "verdict": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        family, _details, crosswalk_sha = validate_bundle(args.root)
        stable = verification_summary(args.root, family, crosswalk_sha)
        comparison_path = args.root / "verification_summary.json"
        if args.no_write:
            if os.path.exists(native(comparison_path)):
                stored = read_json(comparison_path)
                observed_stable = deepcopy(stored)
                observed_stable.pop("runtime_seconds", None)
                if observed_stable != stable:
                    raise ValueError("stored verification summary mismatch")
        else:
            value = {**stable, "runtime_seconds": round(time.perf_counter() - started, 6)}
            write_new_json(comparison_path, value)
    except Exception as error:
        print(f"FAMILY_DEGREE_CERTIFICATE_FAIL|{type(error).__name__}|{error}")
        return 1
    summary = stable["summary"]
    print(
        "FAMILY_DEGREE_CERTIFICATE_PASS|"
        f"S4=min7/d{summary['S4']['degree']}|A4=min11/d{summary['A4']['degree']}|"
        f"S5=d{summary['S5']['degree']}/pairs{summary['S5']['degree_three_colliding_pairs']}|"
        f"A5=d{summary['A5']['degree']}/pairs{summary['A5']['degree_three_colliding_pairs']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
