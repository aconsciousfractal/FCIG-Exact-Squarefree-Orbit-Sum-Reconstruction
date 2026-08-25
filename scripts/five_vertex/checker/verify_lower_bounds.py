#!/usr/bin/env python3
"""Standard-library verifier for the two five-vertex lower-bound DAGs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Sequence


INDEPENDENT_PATH = Path(__file__).resolve().with_name("reconstruct.py")
INDEPENDENT_SPEC = importlib.util.spec_from_file_location(
    "orbit_sum_independent_reconstruct", INDEPENDENT_PATH
)
if INDEPENDENT_SPEC is None or INDEPENDENT_SPEC.loader is None:
    raise ImportError(f"cannot load independent checker: {INDEPENDENT_PATH}")
independent = importlib.util.module_from_spec(INDEPENDENT_SPEC)
sys.modules[INDEPENDENT_SPEC.name] = independent
INDEPENDENT_SPEC.loader.exec_module(independent)


EXPERIMENT = independent.EXPERIMENT


def canonical_bytes(value: object) -> bytes:
    return independent.encoded(value)


def file_hash(path: Path) -> str:
    return independent.digest_file(path)


def normalized(constraints: Sequence[int]) -> tuple[int, ...]:
    retained: list[int] = []
    for mask in sorted(set(constraints), key=lambda value: (value.bit_count(), value)):
        if mask == 0:
            return (0,)
        if any((smaller & mask) == smaller for smaller in retained):
            continue
        retained.append(mask)
    return tuple(retained)


def state_digest(budget: int, constraints: Sequence[int]) -> str:
    return hashlib.sha256(
        canonical_bytes(
            {
                "budget": budget,
                "constraints_hex": [f"{mask:x}" for mask in constraints],
            }
        )
    ).hexdigest()


def exact_separator_mask(
    matrix: Sequence[Sequence[int]], left: int, right: int
) -> int:
    result = 0
    for index, (a, b) in enumerate(zip(matrix[left], matrix[right])):
        if a != b:
            result |= 1 << index
    if result == 0:
        raise AssertionError("explicit proof pair is not separated by the full dictionary")
    return result


def matrix_digest(model: independent.IndependentModel) -> str:
    digest = hashlib.sha256()
    digest.update(b"[")
    for row_index, row in enumerate(model.matrix):
        if row_index:
            digest.update(b",")
        digest.update(json.dumps(list(row), separators=(",", ":")).encode("ascii"))
    digest.update(b"]\n")
    return digest.hexdigest()


def verify_dag(
    proof: dict[str, object],
    model: independent.IndependentModel,
) -> dict[str, object]:
    if proof["experiment_id"] != EXPERIMENT:
        raise ValueError("proof experiment mismatch")
    if proof["coordinate_count"] != len(model.coordinates):
        raise ValueError("proof coordinate count mismatch")
    coordinate_ids = [model.cid(coordinate) for coordinate in model.coordinates]
    if proof["coordinate_ids"] != coordinate_ids:
        raise ValueError("proof coordinate order/encoding mismatch")
    if proof["pattern_count"] != len(model.patterns):
        raise ValueError("proof pattern count mismatch")
    if proof["solver_status_used_as_proof"]:
        raise ValueError("solver status admitted as proof")

    root_masks = []
    pattern_id_checks = 0
    for row in proof["root_constraints_with_explicit_pattern_pairs"]:
        left = int(row["left_pattern_index"])
        right = int(row["right_pattern_index"])
        if not (0 <= left < right < len(model.patterns)):
            raise ValueError("invalid explicit pattern-pair indices")
        if row["left_pattern_id"] != model.pid(model.patterns[left]):
            raise ValueError("left explicit pattern encoding mismatch")
        if row["right_pattern_id"] != model.pid(model.patterns[right]):
            raise ValueError("right explicit pattern encoding mismatch")
        observed = exact_separator_mask(model.matrix, left, right)
        declared = int(row["separator_mask_hex"], 16)
        if observed != declared or row["separator_count"] != observed.bit_count():
            raise ValueError("explicit pair separator mask mismatch")
        root_masks.append(observed)
        pattern_id_checks += 2
    root_constraints = normalized(root_masks)
    if len(root_constraints) != proof["root_constraint_count"]:
        raise ValueError("proof root is not inclusion-minimal/complete")
    lower_budget = int(proof["lower_budget_proved_infeasible"])
    if proof["certified_minimum"] != lower_budget + 1:
        raise ValueError("minimum/lower-budget mismatch")
    if proof["root_input_state_sha256"] != state_digest(lower_budget, root_constraints):
        raise ValueError("root state digest mismatch")

    witness = [int(index) for index in proof["upper_witness_coordinate_indices"]]
    if len(witness) != proof["certified_minimum"] or len(set(witness)) != len(witness):
        raise ValueError("upper witness cardinality/uniqueness mismatch")
    if not all(0 <= index < len(model.coordinates) for index in witness):
        raise ValueError("upper witness coordinate out of range")
    witness_ids = [model.cid(model.coordinates[index]) for index in witness]
    if witness_ids != proof["upper_witness_coordinate_ids"]:
        raise ValueError("upper witness ID encoding mismatch")
    projected = [tuple(row[index] for index in witness) for row in model.matrix]
    if len(set(projected)) != len(projected):
        raise ValueError("upper witness is not injective on all pattern orbits")

    nodes = proof["nodes"]
    if len(nodes) != proof["node_count"]:
        raise ValueError("node count mismatch")
    for index, node in enumerate(nodes):
        if node["node_id"] != index:
            raise ValueError("node IDs are not a complete array index")

    visited: dict[int, tuple[int, tuple[int, ...]]] = {}
    active: set[int] = set()
    observed_leaf_counts: dict[str, int] = {}
    observed_maximum_depth = 0

    def visit(node_id: int, budget: int, constraints: tuple[int, ...], depth: int) -> None:
        nonlocal observed_maximum_depth
        constraints = normalized(constraints)
        expected_state = (budget, constraints)
        if node_id in visited:
            if visited[node_id] != expected_state:
                raise ValueError("DAG node reused for a different state")
            return
        if node_id in active:
            raise ValueError("cycle in branch DAG")
        if not 0 <= node_id < len(nodes):
            raise ValueError("child node ID out of range")
        active.add(node_id)
        node = nodes[node_id]
        if node["input_budget"] != budget:
            raise ValueError("node input budget mismatch")
        if node["input_constraint_count"] != len(constraints):
            raise ValueError("node input constraint count mismatch")
        if node["input_state_sha256"] != state_digest(budget, constraints):
            raise ValueError("node input state hash mismatch")

        reduced = constraints
        reduced_budget = budget
        for step in node["forced_steps"]:
            unit = int(step["unit_constraint_hex"], 16)
            if unit.bit_count() != 1 or unit not in reduced:
                raise ValueError("invalid forced unit constraint")
            coordinate = unit.bit_length() - 1
            if step["forced_coordinate"] != coordinate:
                raise ValueError("wrong forced coordinate")
            reduced_budget -= 1
            reduced = normalized([mask for mask in reduced if not mask & unit])
        if node["reduced_budget"] != reduced_budget:
            raise ValueError("reduced budget mismatch")
        if node["reduced_constraint_count"] != len(reduced):
            raise ValueError("reduced constraint count mismatch")
        if node["reduced_state_sha256"] != state_digest(reduced_budget, reduced):
            raise ValueError("reduced state hash mismatch")

        kind = node["kind"]
        if kind == "LEAF":
            oracle = node["leaf_oracle"]
            observed_leaf_counts[oracle] = observed_leaf_counts.get(oracle, 0) + 1
            if oracle == "EMPTY_CONSTRAINT":
                if reduced != (0,) or node["empty_constraint_hex"] != "0":
                    raise ValueError("invalid empty-constraint leaf")
            elif oracle == "FORCED_BUDGET_EXHAUSTION":
                if reduced_budget >= 0:
                    raise ValueError("forced-budget leaf has nonnegative budget")
            elif oracle == "NONEMPTY_WITH_ZERO_BUDGET":
                if reduced_budget != 0 or not reduced or reduced == (0,):
                    raise ValueError("invalid zero-budget leaf")
                if int(node["witness_constraint_hex"], 16) not in reduced:
                    raise ValueError("zero-budget witness constraint absent")
            elif oracle == "PAIRWISE_DISJOINT_CONSTRAINT_PACKING":
                packing = [int(value, 16) for value in node["packing_constraint_hex"]]
                if node["packing_size"] != len(packing) or len(packing) <= reduced_budget:
                    raise ValueError("packing cardinality does not close the leaf")
                used = 0
                for mask in packing:
                    if mask not in reduced or mask & used:
                        raise ValueError("packing is absent or not pairwise disjoint")
                    used |= mask
            elif oracle == "UNIFORM_MAXIMUM_COVERAGE_BOUND":
                counts = []
                union = 0
                for mask in reduced:
                    union |= mask
                for coordinate in range(len(model.coordinates)):
                    if union & (1 << coordinate):
                        counts.append(sum(bool(mask & (1 << coordinate)) for mask in reduced))
                maximum = max(counts)
                lower = math.ceil(len(reduced) / maximum)
                if (
                    node["constraint_count"] != len(reduced)
                    or node["maximum_constraints_hit_by_one_coordinate"] != maximum
                    or node["lower_bound"] != lower
                    or lower <= reduced_budget
                ):
                    raise ValueError("uniform-coverage leaf arithmetic mismatch")
            else:
                raise ValueError(f"unknown leaf oracle: {oracle}")
        elif kind == "BRANCH":
            branch = int(node["branch_constraint_hex"], 16)
            if branch not in reduced:
                raise ValueError("branch constraint is not in reduced state")
            coordinates = [
                index for index in range(len(model.coordinates)) if branch & (1 << index)
            ]
            declared_order = [int(value) for value in node["branch_coordinates_in_execution_order"]]
            children = node["children"]
            if sorted(declared_order) != coordinates or len(children) != len(coordinates):
                raise ValueError("branch does not cover every separator exactly once")
            if [child["selected_coordinate"] for child in children] != declared_order:
                raise ValueError("branch child/order mismatch")
            for child in children:
                coordinate = int(child["selected_coordinate"])
                child_constraints = normalized(
                    [mask for mask in reduced if not mask & (1 << coordinate)]
                )
                child_budget = reduced_budget - 1
                expected_child_hash = state_digest(child_budget, child_constraints)
                if child["child_input_state_sha256"] != expected_child_hash:
                    raise ValueError("declared child state hash mismatch")
                visit(
                    int(child["child_node_id"]),
                    child_budget,
                    child_constraints,
                    depth + 1,
                )
        else:
            raise ValueError(f"unknown node kind: {kind}")
        observed_maximum_depth = max(observed_maximum_depth, depth)
        active.remove(node_id)
        visited[node_id] = expected_state

    visit(int(proof["root_node_id"]), lower_budget, root_constraints, 0)
    if len(visited) != len(nodes):
        raise ValueError("proof contains unreachable or unchecked nodes")
    if observed_maximum_depth != proof["maximum_depth"]:
        raise ValueError("maximum proof depth mismatch")
    if dict(sorted(observed_leaf_counts.items())) != proof["leaf_oracle_counts"]:
        raise ValueError("leaf-oracle census mismatch")
    return {
        "group": model.name,
        "pattern_count": len(model.patterns),
        "coordinate_count": len(model.coordinates),
        "full_signature_matrix_sha256": matrix_digest(model),
        "explicit_pair_constraint_count": len(root_constraints),
        "explicit_pattern_id_checks": pattern_id_checks,
        "node_count": len(nodes),
        "reachable_node_count": len(visited),
        "maximum_depth": observed_maximum_depth,
        "leaf_oracle_counts": dict(sorted(observed_leaf_counts.items())),
        "lower_budget_infeasible": lower_budget,
        "upper_witness_cardinality": len(witness),
        "certified_minimum": proof["certified_minimum"],
        "upper_witness_injective_on_every_pattern_orbit": True,
        "every_separator_mask_recomputed_from_explicit_patterns": True,
        "every_branch_and_leaf_checked_locally": True,
    }


def load_proof(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    compressed = path.read_bytes()
    raw = gzip.decompress(compressed)
    data = json.loads(raw)
    if canonical_bytes(data) != raw:
        raise ValueError("proof gzip does not contain canonical JSON")
    return data, {
        "path": path.name,
        "compressed_bytes": len(compressed),
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "canonical_json_bytes": len(raw),
        "canonical_json_sha256": hashlib.sha256(raw).hexdigest(),
    }


def run(root: Path, producer_dir: Path, output_dir: Path, check_only: bool) -> int:
    started = time.perf_counter()
    specification = root / "schemas" / "five_vertex_specification.json"
    normalization = root / "docs" / "NORMALIZATION_LOCK.md"
    source_paths = [Path(__file__).resolve(), Path(independent.__file__).resolve()]
    spec = json.loads(specification.read_text(encoding="utf-8"))
    if spec.get("specification_id") != EXPERIMENT:
        raise ValueError("five-vertex specification mismatch")
    if "Cumulative signatures and minima" not in normalization.read_text(encoding="utf-8"):
        raise ValueError("normalization marker missing")
    proof_paths = [
        producer_dir / "branch_dag_S5.json.gz",
        producer_dir / "branch_dag_A5.json.gz",
    ]
    missing = [str(path) for path in proof_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing proof DAGs: {missing}")

    summaries = []
    proof_transports = []
    for group, filename in (
        ("S5", "branch_dag_S5.json.gz"),
        ("A5", "branch_dag_A5.json.gz"),
    ):
        model = independent.reconstruct_model(5, group == "A5")
        proof, transport = load_proof(producer_dir / filename)
        if proof["group"] != group:
            raise ValueError("proof group mismatch")
        summaries.append(verify_dag(proof, model))
        proof_transports.append(transport)
        del proof
        del model

    verdict = "PASS_FIVE_VERTEX_MINIMUM_CERTIFICATES"
    summary_document = {
        "schema": "orbit_sum_lower_bound_verification_v1",
        "experiment_id": EXPERIMENT,
        "checker_independence": {
            "producer_module_imported": False,
            "producer_generated_separator_masks_trusted": False,
            "group_generation": "generator_closure",
            "coordinate_evaluation": "contained_support_subset_accumulation",
            "proof_checker_dependencies": "PYTHON_STANDARD_LIBRARY_ONLY",
        },
        "verified_inputs": [
            {
                "path": path.resolve().relative_to(root.resolve()).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": file_hash(path),
            }
            for path in [specification, normalization, *source_paths, *proof_paths]
        ],
        "proof_transports": proof_transports,
        "group_verification": summaries,
        "encoding_completeness": {
            "all_nodes_array_indexed": True,
            "all_nodes_reachable": True,
            "all_coordinate_ids_reconstructed": True,
            "all_explicit_pattern_ids_reconstructed": True,
            "canonical_json_inside_deterministic_gzip": True,
        },
        "execution": {
            "python": platform.python_version(),
            "optimized_mode": not __debug__,
            "check_only": check_only,
            "wall_seconds": round(time.perf_counter() - started, 6),
            "network_used": False,
            "pdf_extraction_used": False,
            "maximum_n": 5,
            "n_greater_than_5_executed": False,
        },
        "verdict": verdict,
    }
    summary_bytes = canonical_bytes(summary_document)
    if not check_only:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "lower_bound_verification.json").write_bytes(summary_bytes)
    print(
        f"ORBIT_SUM_CHECKER_{verdict}|S5_nodes={summaries[0]['node_count']}|"
        f"A5_nodes={summaries[1]['node_count']}|optimized={not __debug__}|"
        f"summary_sha256={hashlib.sha256(summary_bytes).hexdigest()}|"
        f"seconds={summary_document['execution']['wall_seconds']}"
    )
    return 0


def parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root")
    parser.add_argument("--producer")
    parser.add_argument("--output")
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    root = Path(args.project_root).resolve() if args.project_root else Path(__file__).resolve().parents[3]
    producer = Path(args.producer).resolve() if args.producer else root / "certificates" / "five_vertex"
    output = Path(args.output).resolve() if args.output else root / "tmp" / "five_vertex_checker"
    return run(root, producer, output, args.check_only)


if __name__ == "__main__":
    raise SystemExit(main())
