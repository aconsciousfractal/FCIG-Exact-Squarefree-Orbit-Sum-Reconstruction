#!/usr/bin/env python3
"""Primary exact search for minimum four-vertex separating fingerprints."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Iterable


PROJECT = Path(__file__).resolve().parents[1]
EXPERIMENT = "MINIMUM_FINGERPRINTS"
IMPLEMENTATION_ID = "PRIMARY_EXACT_SEARCH"
SPECIFICATION = PROJECT / "schemas" / "minimum_fingerprints_specification.yaml"
CONTRACT = PROJECT / "schemas" / "minimum_fingerprints_contract_v1.json"
COORDINATES = (
    PROJECT
    / "certificates"
    / "orbit_atlas"
    / "primary"
    / "coordinate_registry.json"
)
PATTERNS = (
    PROJECT
    / "certificates"
    / "orbit_atlas"
    / "primary"
    / "pattern_registry.json"
)
INPUTS = (SPECIFICATION, CONTRACT, COORDINATES, PATTERNS)
EXPECTED = {
    "S4": {"coordinates": 19, "patterns": 218, "pairs": 23653},
    "A4": {"coordinates": 29, "patterns": 368, "pairs": 67528},
}
GROUP_ORDER = ("S4", "A4")
MAX_PROOF_NODES = 1_500_000


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


def load_json(path: Path) -> dict[str, object]:
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


def verify_inputs() -> dict[str, str]:
    missing = [str(path) for path in INPUTS if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing scientific inputs: {missing}")
    return {
        path.relative_to(PROJECT).as_posix(): sha256(path)
        for path in INPUTS
    }


def bit_indices(mask: int) -> list[int]:
    result: list[int] = []
    while mask:
        bit = mask & -mask
        result.append(bit.bit_length() - 1)
        mask ^= bit
    return result


def state_hash(uncovered: tuple[int, ...]) -> str:
    encoded = ",".join(str(index) for index in uncovered).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def canonical_pair_line(
    pair_id: str, left_id: str, right_id: str, separator_mask: int
) -> bytes:
    return (
        json.dumps(
            [pair_id, left_id, right_id, separator_mask],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")


def inclusion_minimal_masks(masks: Iterable[int]) -> list[int]:
    ordered = sorted(set(masks), key=lambda mask: (mask.bit_count(), mask))
    minimal: list[int] = []
    for mask in ordered:
        if not any((candidate & mask) == candidate for candidate in minimal):
            minimal.append(mask)
    return minimal


def build_group_instance(
    group: str,
    coordinate_group: dict[str, object],
    pattern_group: dict[str, object],
) -> tuple[dict[str, object], list[int], list[str]]:
    coordinate_rows = coordinate_group.get("rows")
    pattern_rows = pattern_group.get("rows")
    if not isinstance(coordinate_rows, list) or not isinstance(pattern_rows, list):
        raise TypeError(f"missing rows for {group}")
    coordinate_ids = [str(row["coordinate_id"]) for row in coordinate_rows]
    pattern_ids = [str(row["pattern_id"]) for row in pattern_rows]
    signatures = [list(row["signature_through_3"]) for row in pattern_rows]
    expected = EXPECTED[group]
    if len(coordinate_ids) != expected["coordinates"]:
        raise ValueError(f"{group} coordinate count mismatch")
    if len(pattern_ids) != expected["patterns"]:
        raise ValueError(f"{group} pattern count mismatch")
    if coordinate_ids != sorted(coordinate_ids, key=lambda value: (
        int(value.split("-D")[1][0]), value
    )):
        raise ValueError(f"{group} coordinate order is not canonical")
    if pattern_ids != sorted(pattern_ids):
        raise ValueError(f"{group} pattern order is not canonical")
    if any(len(signature) != len(coordinate_ids) for signature in signatures):
        raise ValueError(f"{group} signature length mismatch")

    pair_hasher = hashlib.sha256()
    mask_records: dict[int, dict[str, object]] = {}
    pair_index = 0
    for left_index, left_id in enumerate(pattern_ids):
        left_signature = signatures[left_index]
        for right_index in range(left_index + 1, len(pattern_ids)):
            right_id = pattern_ids[right_index]
            right_signature = signatures[right_index]
            separator_mask = 0
            for coordinate_index, (left, right) in enumerate(
                zip(left_signature, right_signature, strict=True)
            ):
                if left != right:
                    separator_mask |= 1 << coordinate_index
            if separator_mask == 0:
                raise ValueError(
                    f"{group} empty separator mask for {left_id}, {right_id}"
                )
            pair_id = f"{group}-PAIR-{pair_index:05d}"
            pair_hasher.update(
                canonical_pair_line(pair_id, left_id, right_id, separator_mask)
            )
            record = mask_records.get(separator_mask)
            if record is None:
                mask_records[separator_mask] = {
                    "duplicate_pair_count": 1,
                    "left_pattern_id": left_id,
                    "right_pattern_id": right_id,
                    "witness_pair_id": pair_id,
                }
            else:
                record["duplicate_pair_count"] = int(record["duplicate_pair_count"]) + 1
            pair_index += 1
    if pair_index != expected["pairs"]:
        raise ValueError(f"{group} pair count mismatch: {pair_index}")

    distinct_masks = sorted(mask_records, key=lambda mask: (mask.bit_count(), mask))
    minimal_masks = inclusion_minimal_masks(distinct_masks)
    distinct_rows = []
    for index, mask in enumerate(distinct_masks):
        record = mask_records[mask]
        distinct_rows.append(
            {
                "coordinate_ids": [coordinate_ids[i] for i in bit_indices(mask)],
                "duplicate_pair_count": record["duplicate_pair_count"],
                "left_pattern_id": record["left_pattern_id"],
                "mask_hex": f"0x{mask:0{(len(coordinate_ids) + 3) // 4}x}",
                "mask_int": mask,
                "mask_popcount": mask.bit_count(),
                "right_pattern_id": record["right_pattern_id"],
                "separator_mask_index": index,
                "witness_pair_id": record["witness_pair_id"],
            }
        )
    reduced_rows = []
    for index, mask in enumerate(minimal_masks):
        record = mask_records[mask]
        reduced_rows.append(
            {
                "constraint_id": f"{group}-CON-{index:05d}",
                "coordinate_ids": [coordinate_ids[i] for i in bit_indices(mask)],
                "duplicate_pair_count": record["duplicate_pair_count"],
                "left_pattern_id": record["left_pattern_id"],
                "mask_hex": f"0x{mask:0{(len(coordinate_ids) + 3) // 4}x}",
                "mask_int": mask,
                "mask_popcount": mask.bit_count(),
                "right_pattern_id": record["right_pattern_id"],
                "witness_pair_id": record["witness_pair_id"],
            }
        )
    return (
        {
            "coordinate_count": len(coordinate_ids),
            "coordinate_ids": coordinate_ids,
            "distinct_separator_mask_count": len(distinct_masks),
            "distinct_separator_masks": distinct_rows,
            "full_pair_count": pair_index,
            "full_pair_sha256": pair_hasher.hexdigest(),
            "group": group,
            "inclusion_minimal_constraint_count": len(minimal_masks),
            "inclusion_minimal_constraints": reduced_rows,
            "pattern_count": len(pattern_ids),
            "pattern_ids_sha256": hashlib.sha256(
                ("\n".join(pattern_ids) + "\n").encode("ascii")
            ).hexdigest(),
        },
        minimal_masks,
        coordinate_ids,
    )


def greedy_packing(uncovered: tuple[int, ...], masks: list[int]) -> list[int]:
    orders = (
        sorted(uncovered, key=lambda index: (masks[index].bit_count(), masks[index])),
        sorted(uncovered, key=lambda index: (masks[index].bit_count(), -masks[index])),
        sorted(uncovered, key=lambda index: (masks[index], masks[index].bit_count())),
    )
    best: list[int] = []
    for order in orders:
        used = 0
        chosen: list[int] = []
        for index in order:
            if masks[index] & used == 0:
                chosen.append(index)
                used |= masks[index]
        if len(chosen) > len(best):
            best = chosen
    return best


class ExactTransversal:
    def __init__(self, masks: list[int], coordinate_count: int) -> None:
        self.masks = masks
        self.coordinate_count = coordinate_count
        self.all_constraints = tuple(range(len(masks)))
        self.search_nodes = 0
        self.failed_states: set[tuple[tuple[int, ...], int, int]] = set()

    def uncovered_after(self, uncovered: tuple[int, ...], bit: int) -> tuple[int, ...]:
        return tuple(index for index in uncovered if self.masks[index] & bit == 0)

    def greedy_witness(self) -> int:
        uncovered = self.all_constraints
        selected = 0
        while uncovered:
            gains = []
            for coordinate in range(self.coordinate_count):
                bit = 1 << coordinate
                if selected & bit:
                    continue
                gain = sum(1 for index in uncovered if self.masks[index] & bit)
                gains.append((gain, -coordinate, coordinate))
            gain, _, coordinate = max(gains)
            if gain == 0:
                raise ValueError("constraint family is not coverable")
            bit = 1 << coordinate
            selected |= bit
            uncovered = self.uncovered_after(uncovered, bit)
        for coordinate in reversed(bit_indices(selected)):
            candidate = selected ^ (1 << coordinate)
            if all(mask & candidate for mask in self.masks):
                selected = candidate
        return selected

    def find_completion(
        self,
        uncovered: tuple[int, ...],
        budget: int,
        allowed_mask: int,
    ) -> int | None:
        self.search_nodes += 1
        if not uncovered:
            return 0
        if budget == 0:
            return None
        key = (uncovered, budget, allowed_mask)
        if key in self.failed_states:
            return None
        candidate_masks = [self.masks[index] & allowed_mask for index in uncovered]
        if any(mask == 0 for mask in candidate_masks):
            self.failed_states.add(key)
            return None
        packing = greedy_packing(uncovered, self.masks)
        if len(packing) > budget:
            self.failed_states.add(key)
            return None
        branch_index = min(
            uncovered,
            key=lambda index: (
                (self.masks[index] & allowed_mask).bit_count(),
                self.masks[index].bit_count(),
                self.masks[index],
            ),
        )
        branch_mask = self.masks[branch_index] & allowed_mask
        candidates = bit_indices(branch_mask)
        candidates.sort(
            key=lambda coordinate: (
                -sum(
                    1
                    for index in uncovered
                    if self.masks[index] & (1 << coordinate)
                ),
                coordinate,
            )
        )
        for coordinate in candidates:
            bit = 1 << coordinate
            child = self.uncovered_after(uncovered, bit)
            completion = self.find_completion(
                child, budget - 1, allowed_mask & ~bit
            )
            if completion is not None:
                return bit | completion
        self.failed_states.add(key)
        return None

    def solve(self) -> tuple[int, int, int, int]:
        greedy = self.greedy_witness()
        upper = greedy.bit_count()
        root_packing = greedy_packing(self.all_constraints, self.masks)
        lower = len(root_packing)
        witness: int | None = None
        for size in range(lower, upper + 1):
            self.failed_states.clear()
            candidate = self.find_completion(
                self.all_constraints,
                size,
                (1 << self.coordinate_count) - 1,
            )
            if candidate is not None:
                witness = candidate
                optimum = candidate.bit_count()
                break
        if witness is None:
            raise RuntimeError("exact search failed to recover the greedy incumbent")
        if optimum > upper:
            raise AssertionError("optimum exceeds incumbent")
        return optimum, witness, greedy, lower

    def lexicographically_first(self, optimum: int) -> int:
        selected = 0
        uncovered = self.all_constraints
        previous = -1
        for position in range(optimum):
            remaining = optimum - position - 1
            latest = self.coordinate_count - (remaining + 1)
            chosen: int | None = None
            for coordinate in range(previous + 1, latest + 1):
                bit = 1 << coordinate
                child = self.uncovered_after(uncovered, bit)
                allowed = ((1 << self.coordinate_count) - 1) ^ (
                    (1 << (coordinate + 1)) - 1
                )
                self.failed_states.clear()
                completion = self.find_completion(child, remaining, allowed)
                if completion is not None:
                    chosen = coordinate
                    break
            if chosen is None:
                raise RuntimeError("failed to construct lexicographic optimum")
            bit = 1 << chosen
            selected |= bit
            uncovered = self.uncovered_after(uncovered, bit)
            previous = chosen
        if uncovered:
            raise AssertionError("lexicographic optimum does not hit every constraint")
        return selected


def find_disjoint_packing(
    masks: list[int], need: int, call_cap: int = 2_000_000
) -> tuple[list[int] | None, int, bool]:
    root = tuple(sorted(range(len(masks)), key=lambda i: (masks[i].bit_count(), masks[i])))
    greedy = greedy_packing(root, masks)
    if len(greedy) >= need:
        return greedy[:need], 0, True
    calls = 0
    aborted = False

    def search(candidates: tuple[int, ...], used: int, remaining: int) -> list[int] | None:
        nonlocal calls, aborted
        calls += 1
        if calls > call_cap:
            aborted = True
            return None
        if remaining == 0:
            return []
        compatible = tuple(index for index in candidates if masks[index] & used == 0)
        if len(compatible) < remaining:
            return None
        if (29 - used.bit_count()) < remaining:
            return None
        for position, index in enumerate(compatible):
            mask = masks[index]
            future = tuple(
                other
                for other in compatible[position + 1 :]
                if masks[other] & (used | mask) == 0
            )
            if len(future) < remaining - 1:
                continue
            result = search(future, used | mask, remaining - 1)
            if result is not None:
                return [index, *result]
            if aborted:
                return None
        return None

    result = search(root, 0, need)
    return result, calls, not aborted


class ProofDagBuilder:
    def __init__(self, group: str, masks: list[int], budget: int) -> None:
        self.group = group
        self.masks = masks
        self.root_state = tuple(range(len(masks)))
        self.root_budget = budget
        self.nodes: list[dict[str, object] | None] = []
        self.memo: dict[tuple[tuple[int, ...], int], str] = {}

    def node_id(self, index: int) -> str:
        return f"{self.group}-N{index:07d}"

    def prove(self, uncovered: tuple[int, ...], budget: int) -> str:
        if not uncovered:
            raise ValueError("lower-bound target is feasible; proof cannot close")
        key = (uncovered, budget)
        previous = self.memo.get(key)
        if previous is not None:
            return previous
        if len(self.nodes) >= MAX_PROOF_NODES:
            raise RuntimeError("branch-DAG node cap exceeded")
        index = len(self.nodes)
        identifier = self.node_id(index)
        self.memo[key] = identifier
        self.nodes.append(None)
        common: dict[str, object] = {
            "budget": budget,
            "node_id": identifier,
            "uncovered_count": len(uncovered),
            "uncovered_sha256": state_hash(uncovered),
        }
        if budget == 0:
            node = {**common, "kind": "budget_zero"}
        else:
            packing = greedy_packing(uncovered, self.masks)
            if len(packing) > budget:
                node = {
                    **common,
                    "kind": "packing_leaf",
                    "packing_constraint_indices": packing[: budget + 1],
                }
            else:
                branch_index = min(
                    uncovered,
                    key=lambda item: (
                        self.masks[item].bit_count(),
                        self.masks[item],
                    ),
                )
                children = []
                for coordinate in bit_indices(self.masks[branch_index]):
                    bit = 1 << coordinate
                    child_state = tuple(
                        item for item in uncovered if self.masks[item] & bit == 0
                    )
                    child_id = self.prove(child_state, budget - 1)
                    children.append(
                        {"coordinate_index": coordinate, "node_id": child_id}
                    )
                node = {
                    **common,
                    "branch_constraint_index": branch_index,
                    "children": children,
                    "kind": "branch",
                }
        self.nodes[index] = node
        return identifier

    def build(self) -> dict[str, object]:
        root = self.prove(self.root_state, self.root_budget)
        if any(node is None for node in self.nodes):
            raise AssertionError("incomplete proof DAG")
        return {
            "certificate_type": "complete_branch_dag_v1",
            "nodes": self.nodes,
            "proof_node_count": len(self.nodes),
            "root_budget": self.root_budget,
            "root_node_id": root,
            "root_uncovered_count": len(self.root_state),
            "root_uncovered_sha256": state_hash(self.root_state),
        }


def packing_certificate(
    group: str,
    indices: list[int],
    instance_group: dict[str, object],
) -> dict[str, object]:
    constraints = instance_group["inclusion_minimal_constraints"]
    if not isinstance(constraints, list):
        raise TypeError("invalid instance constraints")
    witnesses = []
    used = 0
    for index in indices:
        row = constraints[index]
        mask = int(row["mask_int"])
        if used & mask:
            raise AssertionError("packing producer emitted overlapping masks")
        used |= mask
        witnesses.append(
            {
                "constraint_id": row["constraint_id"],
                "constraint_index": index,
                "left_pattern_id": row["left_pattern_id"],
                "mask_hex": row["mask_hex"],
                "mask_int": mask,
                "right_pattern_id": row["right_pattern_id"],
                "witness_pair_id": row["witness_pair_id"],
            }
        )
    return {
        "certificate_type": "pairwise_disjoint_separator_packing_v1",
        "group": group,
        "packing_size": len(witnesses),
        "union_mask_int": used,
        "witnesses": witnesses,
    }


def run(output: Path) -> dict[str, object]:
    started = time.perf_counter()
    if path_exists(output) and any(output.iterdir()):
        raise FileExistsError(f"refusing nonempty output directory: {output}")
    input_hashes = verify_inputs()
    coordinate_registry = load_json(COORDINATES)
    pattern_registry = load_json(PATTERNS)
    coordinate_groups = {
        str(row["group"]): row for row in coordinate_registry["groups"]
    }
    pattern_groups = {str(row["group"]): row for row in pattern_registry["groups"]}

    instance_groups = []
    solution_groups = []
    certificate_groups = []
    summary: dict[str, object] = {}
    for group in GROUP_ORDER:
        instance_group, masks, coordinate_ids = build_group_instance(
            group, coordinate_groups[group], pattern_groups[group]
        )
        solver = ExactTransversal(masks, len(coordinate_ids))
        optimum, any_witness, greedy, initial_lower = solver.solve()
        lex_witness = solver.lexicographically_first(optimum)
        if lex_witness.bit_count() != optimum:
            raise AssertionError("lexicographic witness cardinality mismatch")
        if not all(mask & lex_witness for mask in masks):
            raise AssertionError("lexicographic witness is infeasible")

        packing, packing_calls, packing_search_complete = find_disjoint_packing(
            masks, optimum
        )
        if packing is not None:
            certificate = packing_certificate(group, packing, instance_group)
            certificate["packing_search_calls"] = packing_calls
            certificate["packing_search_complete"] = packing_search_complete
        else:
            dag = ProofDagBuilder(group, masks, optimum - 1).build()
            certificate = {
                **dag,
                "group": group,
                "packing_search_calls": packing_calls,
                "packing_search_complete": packing_search_complete,
            }
        certificate["claimed_lower_bound"] = optimum
        certificate_groups.append(certificate)

        selected_ids = [
            coordinate_ids[index] for index in bit_indices(lex_witness)
        ]
        solution_groups.append(
            {
                "all_full_pairs_separated": True,
                "canonical_coordinate_ids": selected_ids,
                "canonical_coordinate_mask_int": lex_witness,
                "coordinate_count": len(coordinate_ids),
                "full_pair_count": instance_group["full_pair_count"],
                "full_pair_sha256": instance_group["full_pair_sha256"],
                "greedy_coordinate_ids": [
                    coordinate_ids[index] for index in bit_indices(greedy)
                ],
                "greedy_upper_bound": greedy.bit_count(),
                "group": group,
                "initial_disjoint_packing_lower_bound": initial_lower,
                "minimum_size": optimum,
                "reduced_constraint_count": len(masks),
                "search_nodes": solver.search_nodes,
            }
        )
        instance_groups.append(instance_group)
        summary[group] = {
            "canonical_coordinate_ids": selected_ids,
            "certificate_type": certificate["certificate_type"],
            "distinct_separator_masks": instance_group[
                "distinct_separator_mask_count"
            ],
            "full_pairs": instance_group["full_pair_count"],
            "greedy_upper_bound": greedy.bit_count(),
            "minimum_size": optimum,
            "reduced_constraints": len(masks),
        }

    instance = {
        "experiment_id": EXPERIMENT,
        "groups": instance_groups,
        "reduction": "duplicate_collapse_then_exact_inclusion_minimal_masks",
        "schema_version": "minimum_fingerprints_instance_v1",
    }
    solutions = {
        "experiment_id": EXPERIMENT,
        "groups": solution_groups,
        "objective": "global_minimum_separating_fingerprint",
        "schema_version": "minimum_fingerprints_minimum_fingerprints_v1",
    }
    certificates = {
        "experiment_id": EXPERIMENT,
        "groups": certificate_groups,
        "schema_version": "minimum_fingerprints_lower_bound_certificate_v1",
    }
    output.mkdir(parents=True, exist_ok=True)
    instance_path = output / "instance.json"
    solution_path = output / "minimum_fingerprints.json"
    certificate_path = output / "lower_bound_certificate.json"
    save_json(instance_path, instance)
    save_json(solution_path, solutions)
    save_json(certificate_path, certificates)
    build_summary = {
        "artifact_hashes": {
            "instance.json": sha256(instance_path),
            "lower_bound_certificate.json": sha256(certificate_path),
            "minimum_fingerprints.json": sha256(solution_path),
        },
        "experiment_id": EXPERIMENT,
        "implementation": "json_instance_plus_proof_producing_exact_transversal_search",
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
        print(f"MINIMUM_FINGERPRINTS_PRIMARY_FAIL|{type(error).__name__}|{error}")
        return 1
    print(
        "MINIMUM_FINGERPRINTS_PRIMARY_PASS|"
        + "|".join(
            f"{group}=min{build_summary['summary'][group]['minimum_size']}"
            f"/ub{build_summary['summary'][group]['greedy_upper_bound']}"
            f"/{build_summary['summary'][group]['certificate_type']}"
            for group in GROUP_ORDER
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
