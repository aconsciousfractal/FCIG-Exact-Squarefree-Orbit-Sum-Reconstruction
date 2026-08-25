#!/usr/bin/env python3
"""Independent CSV/coverage-bitset exact fingerprint solver."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import time


PROJECT = Path(__file__).resolve().parents[1]
EXPERIMENT = "MINIMUM_FINGERPRINTS"
IMPLEMENTATION_ID = "INDEPENDENT_EXACT_SEARCH"
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
EXPECTED = {
    "S4": {"coordinates": 19, "patterns": 218, "pairs": 23653},
    "A4": {"coordinates": 29, "patterns": 368, "pairs": 67528},
}
GROUP_ORDER = ("S4", "A4")


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


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(native(path), "w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def path_exists(path: Path) -> bool:
    return os.path.exists(native(path))


def verify_inputs() -> dict[str, str]:
    missing = [str(path) for path in INPUTS if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing scientific inputs: {missing}")
    return {path.relative_to(PROJECT).as_posix(): sha256(path) for path in INPUTS}


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


def minimal_separator_masks(masks: set[int]) -> list[int]:
    ordered = sorted(masks, key=lambda value: (value.bit_count(), value))
    answer: list[int] = []
    for mask in ordered:
        dominated = False
        for smaller in answer:
            if smaller & mask == smaller:
                dominated = True
                break
        if not dominated:
            answer.append(mask)
    return answer


def greedy_disjoint(uncovered: int, masks: list[int]) -> list[int]:
    indices = []
    value = uncovered
    while value:
        bit = value & -value
        indices.append(bit.bit_length() - 1)
        value ^= bit
    orders = (
        sorted(indices, key=lambda i: (masks[i].bit_count(), masks[i])),
        sorted(indices, key=lambda i: (masks[i].bit_count(), -masks[i])),
    )
    best: list[int] = []
    for order in orders:
        union = 0
        chosen: list[int] = []
        for index in order:
            if masks[index] & union == 0:
                chosen.append(index)
                union |= masks[index]
        if len(chosen) > len(best):
            best = chosen
    return best


class CoverageSolver:
    def __init__(self, masks: list[int], coordinate_count: int) -> None:
        self.masks = masks
        self.coordinate_count = coordinate_count
        self.coverage = [0] * coordinate_count
        for constraint_index, mask in enumerate(masks):
            constraint_bit = 1 << constraint_index
            for coordinate in bits(mask):
                self.coverage[coordinate] |= constraint_bit
        self.full = (1 << len(masks)) - 1
        self.failed: set[tuple[int, int, int]] = set()
        self.nodes = 0

    def greedy(self) -> int:
        uncovered = self.full
        selected = 0
        while uncovered:
            candidates = [
                ((self.coverage[c] & uncovered).bit_count(), -c, c)
                for c in range(self.coordinate_count)
                if selected & (1 << c) == 0
            ]
            gain, _, coordinate = max(candidates)
            if gain == 0:
                raise ValueError("uncoverable constraint family")
            selected |= 1 << coordinate
            uncovered &= ~self.coverage[coordinate]
        for coordinate in reversed(bits(selected)):
            candidate = selected ^ (1 << coordinate)
            cover = 0
            for other in bits(candidate):
                cover |= self.coverage[other]
            if cover == self.full:
                selected = candidate
        return selected

    def search(self, uncovered: int, budget: int, allowed: int) -> int | None:
        self.nodes += 1
        if uncovered == 0:
            return 0
        if budget == 0:
            return None
        key = (uncovered, budget, allowed)
        if key in self.failed:
            return None
        available = bits(allowed)
        gains = [
            (self.coverage[coordinate] & uncovered).bit_count()
            for coordinate in available
        ]
        maximum = max(gains, default=0)
        if maximum == 0:
            self.failed.add(key)
            return None
        cardinality_bound = (uncovered.bit_count() + maximum - 1) // maximum
        if cardinality_bound > budget:
            self.failed.add(key)
            return None
        packing = greedy_disjoint(uncovered, self.masks)
        if len(packing) > budget:
            self.failed.add(key)
            return None

        constraint_indices = bits(uncovered)
        branch = min(
            constraint_indices,
            key=lambda index: (
                (self.masks[index] & allowed).bit_count(),
                self.masks[index].bit_count(),
                self.masks[index],
            ),
        )
        branch_mask = self.masks[branch] & allowed
        if branch_mask == 0:
            self.failed.add(key)
            return None
        coordinates = bits(branch_mask)
        coordinates.sort(
            key=lambda coordinate: (
                -(self.coverage[coordinate] & uncovered).bit_count(),
                coordinate,
            )
        )
        for coordinate in coordinates:
            bit = 1 << coordinate
            child = uncovered & ~self.coverage[coordinate]
            completion = self.search(child, budget - 1, allowed & ~bit)
            if completion is not None:
                return bit | completion
        self.failed.add(key)
        return None

    def solve(self) -> tuple[int, int, int, int]:
        greedy = self.greedy()
        upper = greedy.bit_count()
        lower = len(greedy_disjoint(self.full, self.masks))
        witness: int | None = None
        for size in range(lower, upper + 1):
            self.failed.clear()
            witness = self.search(
                self.full, size, (1 << self.coordinate_count) - 1
            )
            if witness is not None:
                break
        if witness is None:
            raise RuntimeError("search did not recover an incumbent")
        optimum = witness.bit_count()
        return optimum, witness, greedy, lower

    def lex_first(self, optimum: int) -> int:
        selected = 0
        uncovered = self.full
        previous = -1
        for position in range(optimum):
            remaining = optimum - position - 1
            latest = self.coordinate_count - remaining - 1
            chosen: int | None = None
            for coordinate in range(previous + 1, latest + 1):
                child = uncovered & ~self.coverage[coordinate]
                allowed = ((1 << self.coordinate_count) - 1) ^ (
                    (1 << (coordinate + 1)) - 1
                )
                self.failed.clear()
                if self.search(child, remaining, allowed) is not None:
                    chosen = coordinate
                    break
            if chosen is None:
                raise RuntimeError("lexicographic optimum construction failed")
            selected |= 1 << chosen
            uncovered &= ~self.coverage[chosen]
            previous = chosen
        if uncovered:
            raise AssertionError("canonical witness is not feasible")
        return selected


def build_group(
    group: str,
    coordinate_rows: list[dict[str, str]],
    pattern_rows: list[dict[str, str]],
) -> tuple[
    list[str], list[str], list[list[int]], list[int], str, int, int, list[int]
]:
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
    if any(len(signature) != len(coordinate_ids) for signature in signatures):
        raise ValueError(f"{group} signature width mismatch")
    if pattern_ids != sorted(pattern_ids):
        raise ValueError(f"{group} pattern ordering mismatch")

    full_masks: list[int] = []
    distinct: set[int] = set()
    hasher = hashlib.sha256()
    pair_index = 0
    for left_index in range(len(pattern_ids)):
        for right_index in range(left_index + 1, len(pattern_ids)):
            mask = 0
            for coordinate, values in enumerate(
                zip(signatures[left_index], signatures[right_index], strict=True)
            ):
                if values[0] != values[1]:
                    mask |= 1 << coordinate
            if mask == 0:
                raise ValueError(f"{group} has an unseparated full pair")
            pair_id = f"{group}-PAIR-{pair_index:05d}"
            hasher.update(
                pair_line(
                    pair_id,
                    pattern_ids[left_index],
                    pattern_ids[right_index],
                    mask,
                )
            )
            full_masks.append(mask)
            distinct.add(mask)
            pair_index += 1
    if pair_index != expected["pairs"]:
        raise ValueError(f"{group} full pair count mismatch")
    minimal = minimal_separator_masks(distinct)
    return (
        coordinate_ids,
        pattern_ids,
        signatures,
        full_masks,
        hasher.hexdigest(),
        len(distinct),
        len(minimal),
    ) + (minimal,)


def run(output: Path) -> dict[str, object]:
    started = time.perf_counter()
    if path_exists(output) and any(output.iterdir()):
        raise FileExistsError(f"refusing nonempty output directory: {output}")
    input_hashes = verify_inputs()
    coordinate_rows = read_csv(COORDINATE_CSV)
    pattern_rows = read_csv(PATTERN_CSV)
    groups = []
    summary: dict[str, object] = {}
    for group in GROUP_ORDER:
        built = build_group(group, coordinate_rows, pattern_rows)
        coordinate_ids = built[0]
        full_masks = built[3]
        full_pair_hash = built[4]
        distinct_count = built[5]
        reduced_count = built[6]
        minimal_masks = built[7]
        solver = CoverageSolver(minimal_masks, len(coordinate_ids))
        optimum, _, greedy, initial_lower = solver.solve()
        canonical = solver.lex_first(optimum)
        if not all(mask & canonical for mask in full_masks):
            raise AssertionError(f"{group} canonical witness misses a full pair")
        selected_ids = [coordinate_ids[index] for index in bits(canonical)]
        row = {
            "all_full_pairs_separated": True,
            "canonical_coordinate_ids": selected_ids,
            "canonical_coordinate_mask_int": canonical,
            "coordinate_count": len(coordinate_ids),
            "distinct_separator_mask_count": distinct_count,
            "full_pair_count": len(full_masks),
            "full_pair_sha256": full_pair_hash,
            "greedy_coordinate_ids": [
                coordinate_ids[index] for index in bits(greedy)
            ],
            "greedy_upper_bound": greedy.bit_count(),
            "group": group,
            "initial_disjoint_packing_lower_bound": initial_lower,
            "minimum_size": optimum,
            "reduced_constraint_count": reduced_count,
            "search_nodes": solver.nodes,
        }
        groups.append(row)
        summary[group] = {
            "canonical_coordinate_ids": selected_ids,
            "distinct_separator_masks": distinct_count,
            "full_pairs": len(full_masks),
            "greedy_upper_bound": greedy.bit_count(),
            "minimum_size": optimum,
            "reduced_constraints": reduced_count,
        }
    output.mkdir(parents=True, exist_ok=True)
    solution = {
        "experiment_id": EXPERIMENT,
        "groups": groups,
        "objective": "global_minimum_separating_fingerprint",
        "schema_version": "minimum_fingerprints_minimum_fingerprints_v1",
    }
    solution_path = output / "minimum_fingerprints.json"
    save_json(solution_path, solution)
    build_summary = {
        "artifact_hashes": {"minimum_fingerprints.json": sha256(solution_path)},
        "experiment_id": EXPERIMENT,
        "implementation": "independent_csv_parser_plus_pair_coverage_bitset_branch_and_bound",
        "independence_declaration": {
            "consumed_e00": False,
            "consumed_other_implementation": False,
            "consumed_phase3": False,
            "shared_scientific_code": [],
        },
        "input_hashes": input_hashes,
        "random_seed": None,
        "implementation_id": IMPLEMENTATION_ID,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "schema_version": "minimum_fingerprints_build_summary_v1",
        "summary": summary,
        "verdict": "PASS",
    }
    save_json(output / "build_summary.json", build_summary)
    return build_summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else PROJECT / args.output
    try:
        build_summary = run(output)
    except Exception as error:
        print(f"MINIMUM_FINGERPRINTS_INDEPENDENT_FAIL|{type(error).__name__}|{error}")
        return 1
    print(
        "MINIMUM_FINGERPRINTS_INDEPENDENT_PASS|"
        + "|".join(
            f"{group}=min{build_summary['summary'][group]['minimum_size']}"
            f"/ub{build_summary['summary'][group]['greedy_upper_bound']}"
            for group in GROUP_ORDER
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
