#!/usr/bin/env python3
"""Verify the structural certificates added in repository version 2.1.0.

The numerical minima are verified elsewhere.  This checker reconstructs the
complete four-vertex optimum landscapes, the signed A5 blind block, and the
A4 exchange-graph action from the distributed finite payloads.  Factor labels
and a unit minor are treated as witnesses and are checked, not trusted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import sys
from collections import Counter, deque
from fractions import Fraction
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, Sequence


class StructuralCertificateError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StructuralCertificateError(message)


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_value(value: object) -> str:
    return digest_bytes(canonical_json_bytes(value))


def determinant(matrix: Sequence[Sequence[int]]) -> int:
    size = len(matrix)
    require(all(len(row) == size for row in matrix), "determinant matrix is not square")
    if size == 0:
        return 1
    work = [[Fraction(value) for value in row] for row in matrix]
    answer = Fraction(1)
    for column in range(size):
        pivot_row = next(
            (row for row in range(column, size) if work[row][column] != 0),
            None,
        )
        if pivot_row is None:
            return 0
        if pivot_row != column:
            work[column], work[pivot_row] = work[pivot_row], work[column]
            answer = -answer
        pivot = work[column][column]
        answer *= pivot
        for row in range(column + 1, size):
            factor = work[row][column] / pivot
            for index in range(column, size):
                work[row][index] -= factor * work[column][index]
    require(answer.denominator == 1, "integer determinant became nonintegral")
    return answer.numerator


def exact_rank(matrix: Sequence[Sequence[int]]) -> int:
    if not matrix:
        return 0
    work = [[Fraction(value) for value in row] for row in matrix]
    row_count = len(work)
    column_count = len(work[0])
    rank = 0
    for column in range(column_count):
        pivot = next(
            (row for row in range(rank, row_count) if work[row][column] != 0),
            None,
        )
        if pivot is None:
            continue
        work[rank], work[pivot] = work[pivot], work[rank]
        scale = work[rank][column]
        work[rank] = [value / scale for value in work[rank]]
        for row in range(row_count):
            if row == rank or work[row][column] == 0:
                continue
            factor = work[row][column]
            work[row] = [
                work[row][index] - factor * work[rank][index]
                for index in range(column_count)
            ]
        rank += 1
        if rank == row_count:
            break
    return rank


def integer_inverse(matrix: Sequence[Sequence[int]]) -> list[list[int]]:
    size = len(matrix)
    work = [
        [Fraction(value) for value in row]
        + [Fraction(int(i == j)) for j in range(size)]
        for i, row in enumerate(matrix)
    ]
    for column in range(size):
        pivot = next(
            (row for row in range(column, size) if work[row][column] != 0),
            None,
        )
        require(pivot is not None, "singular unit minor")
        work[column], work[pivot] = work[pivot], work[column]
        scale = work[column][column]
        work[column] = [value / scale for value in work[column]]
        for row in range(size):
            if row == column:
                continue
            factor = work[row][column]
            work[row] = [
                work[row][index] - factor * work[column][index]
                for index in range(2 * size)
            ]
    inverse = [row[size:] for row in work]
    require(
        all(value.denominator == 1 for row in inverse for value in row),
        "unit-minor inverse is not integral",
    )
    return [[value.numerator for value in row] for row in inverse]


def multiply(
    left: Sequence[Sequence[int]], right: Sequence[Sequence[int]]
) -> list[list[int]]:
    return [
        [
            sum(
                left[row][inner] * right[inner][column]
                for inner in range(len(right))
            )
            for column in range(len(right[0]))
        ]
        for row in range(len(left))
    ]


def canonical_sign(vector: Sequence[int]) -> tuple[int, ...]:
    values = tuple(vector)
    first = next((value for value in values if value), None)
    require(first is not None, "zero row in the signed blind block")
    return values if first > 0 else tuple(-value for value in values)


def short_id(value: str) -> str:
    return value.rsplit(":", 1)[-1]


def parse_signed_matrix(
    data: bytes,
) -> tuple[list[str], dict[tuple[str, str], dict[str, object]]]:
    rows = list(csv.reader(StringIO(data.decode("utf-8"), newline="")))
    require(bool(rows), "empty signed matrix")
    require(
        rows[0][:3] == ["a5_pattern_1", "a5_pattern_2", "s5_parent"],
        "signed-matrix header drift",
    )
    columns = rows[0][3:]
    require(len(columns) == 35 and len(set(columns)) == 35, "signed-matrix columns")
    parsed: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows[1:]:
        require(len(row) == len(rows[0]), "signed-matrix row width")
        key = (row[0], row[1])
        require(key not in parsed, f"duplicate signed-matrix row {key}")
        parsed[key] = {
            "parent": row[2],
            "values": tuple(int(value) for value in row[3:]),
        }
    require(len(parsed) == 54, "signed-matrix row count")
    return columns, parsed


def derive_a5_rows(
    payload: dict[str, Any],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    a5 = payload["groups"]["A5"]
    tree_children = {
        row["coordinate_id"]
        for row in a5["coordinate_metadata"]
        if row["degree"] == 4
        and row["support_class"]["category"] == "TREE_ON_ALL_VERTICES"
    }
    split: list[tuple[str, str]] = []
    blind: list[tuple[str, str]] = []
    split_indices: list[int] = []
    blind_indices: list[int] = []
    for index, row in enumerate(a5["residual_pairs"]):
        parents = row["S_parent_orbit_ids"]
        is_split = len(parents) == 2 and parents[0] == parents[1]
        require(bool(row["index_two_split_pair"]) == is_split, "split marker drift")
        if not is_split:
            continue
        split_indices.append(index)
        key = tuple(short_id(value) for value in row["pair_id"])
        require(len(key) == 2, "split-pair identifier width")
        split.append(key)
        is_blind = tree_children.isdisjoint(row["separator_coordinate_ids"])
        require(bool(row["tree_blind"]) == is_blind, "tree-blind marker drift")
        if is_blind:
            blind.append(key)
            blind_indices.append(index)
    require(split_indices == a5["index_two_split_pair_indices"], "split-index drift")
    require(blind_indices == a5["tree_blind_pair_indices"], "blind-index drift")
    require(len(split) == 54 and len(blind) == 8, "A5 split/blind census")
    return split, blind


def minimum_covers(row_sets: Sequence[set[str]]) -> tuple[int, list[tuple[str, ...]]]:
    universe = sorted(set().union(*row_sets))
    for size in range(1, len(universe) + 1):
        covers = [
            choice
            for choice in itertools.combinations(universe, size)
            if all(set(choice) & row for row in row_sets)
        ]
        if covers:
            return size, covers
    raise StructuralCertificateError("blind rows have no parent cover")


def determinantal_divisors(
    matrix: Sequence[Sequence[int]],
) -> tuple[list[int], list[int], list[int]]:
    divisors: list[int] = []
    totals: list[int] = []
    nonzero_counts: list[int] = []
    for size in range(1, len(matrix) + 1):
        gcd_value = 0
        total = 0
        nonzero = 0
        for rows in itertools.combinations(range(len(matrix)), size):
            for columns in itertools.combinations(range(len(matrix[0])), size):
                value = abs(
                    determinant(
                        [[matrix[row][column] for column in columns] for row in rows]
                    )
                )
                total += 1
                if value:
                    nonzero += 1
                    gcd_value = math.gcd(gcd_value, value)
        divisors.append(gcd_value)
        totals.append(total)
        nonzero_counts.append(nonzero)
    return divisors, totals, nonzero_counts


def compute_a5(payload: dict[str, Any], matrix_data: bytes) -> dict[str, object]:
    split_keys, blind_keys = derive_a5_rows(payload)
    columns, parsed = parse_signed_matrix(matrix_data)
    require(set(parsed) == set(split_keys), "signed matrix does not join to split rows")
    s5_metadata = {
        row["representative_hex"]: row
        for row in payload["groups"]["S5"]["coordinate_metadata"]
        if row["degree"] == 4
    }
    require(set(columns) <= set(s5_metadata), "signed parent absent from S5 metadata")
    tree_columns = [
        column
        for column in columns
        if s5_metadata[column]["support_class"]["category"]
        == "TREE_ON_ALL_VERTICES"
    ]
    non_tree_columns = [column for column in columns if column not in set(tree_columns)]
    require((len(tree_columns), len(non_tree_columns)) == (14, 21), "A5 parent split")
    column_index = {column: index for index, column in enumerate(columns)}

    full_matrix = [list(parsed[key]["values"]) for key in split_keys]
    blind_matrix = [list(parsed[key]["values"]) for key in blind_keys]
    tree_indices = [column_index[column] for column in tree_columns]
    non_tree_indices = [column_index[column] for column in non_tree_columns]
    require(
        all(row[index] == 0 for row in blind_matrix for index in tree_indices),
        "tree-parent entry on a tree-blind row",
    )

    ranks = {
        "all_rows_all_parents": exact_rank(full_matrix),
        "all_rows_tree_parents": exact_rank(
            [[row[index] for index in tree_indices] for row in full_matrix]
        ),
        "all_rows_non_tree_parents": exact_rank(
            [[row[index] for index in non_tree_indices] for row in full_matrix]
        ),
        "blind_rows_all_parents": exact_rank(blind_matrix),
        "blind_rows_tree_parents": exact_rank(
            [[row[index] for index in tree_indices] for row in blind_matrix]
        ),
        "blind_rows_non_tree_parents": exact_rank(
            [[row[index] for index in non_tree_indices] for row in blind_matrix]
        ),
    }
    require(
        ranks
        == {
            "all_rows_all_parents": 24,
            "all_rows_tree_parents": 14,
            "all_rows_non_tree_parents": 20,
            "blind_rows_all_parents": 4,
            "blind_rows_tree_parents": 0,
            "blind_rows_non_tree_parents": 4,
        },
        "signed-matrix rank drift",
    )

    classes: dict[tuple[int, ...], list[dict[str, object]]] = {}
    for key in blind_keys:
        values = tuple(parsed[key]["values"][index] for index in non_tree_indices)
        normalized = canonical_sign(values)
        classes.setdefault(normalized, []).append(
            {
                "a5_pattern_pair": list(key),
                "s5_pattern_parent": parsed[key]["parent"],
                "orientation_sign": 1 if values == normalized else -1,
            }
        )
    require(len(classes) == 4, "signed-class count")
    require(sorted(map(len, classes.values())) == [2, 2, 2, 2], "class multiplicity")
    basis = sorted(classes)

    unit: tuple[tuple[int, ...], int] | None = None
    for chosen in itertools.combinations(range(len(non_tree_columns)), 4):
        value = determinant([[row[index] for index in chosen] for row in basis])
        if abs(value) == 1:
            unit = (chosen, value)
            break
    require(unit is not None, "no determinant-one blind minor")
    chosen, det_value = unit
    minor = [[row[index] for index in chosen] for row in basis]
    inverse = integer_inverse(minor)
    identity = [[int(row == column) for column in range(4)] for row in range(4)]
    require(multiply(minor, inverse) == identity, "unit-minor right inverse")
    require(multiply(inverse, minor) == identity, "unit-minor left inverse")
    divisors, minor_counts, nonzero_counts = determinantal_divisors(basis)
    require(divisors == [1, 1, 1, 1], "determinantal divisors")
    smith = [divisors[0]] + [
        divisors[index] // divisors[index - 1] for index in range(1, 4)
    ]
    require(smith == [1, 1, 1, 1], "Smith invariant factors")

    blind_sets = [
        {
            columns[index]
            for index, value in enumerate(parsed[key]["values"])
            if value and columns[index] in set(non_tree_columns)
        }
        for key in blind_keys
    ]
    cover_size, covers = minimum_covers(blind_sets)
    forced_rows = sum(row == {"00115"} for row in blind_sets)
    require(cover_size == 2 and len(covers) == 10, "blind parent-cover census")
    require(forced_rows == 2, "forced parent is not uniquely required by two rows")
    require(all("00115" in cover for cover in covers), "minimum cover omits forced parent")
    a5_quartic_ids = {
        row["coordinate_id"]
        for row in payload["groups"]["A5"]["coordinate_metadata"]
        if row["degree"] == 4
    }
    forced_children = ["A5:5:4:00115", "A5:5:4:00116"]
    require(set(forced_children) <= a5_quartic_ids, "forced A5 child missing")
    s5 = payload["groups"]["S5"]
    arcs = [tuple(arc) for arc in s5["arc_order"]]
    mask = int("00115", 16)
    directed_arcs = [list(arcs[index]) for index in range(len(arcs)) if mask & (1 << index)]

    class_rows = [
        {
            "normalized_non_tree_vector": list(vector),
            "sparse_nonzero_entries": {
                column: value
                for column, value in zip(non_tree_columns, vector)
                if value
            },
            "row_members": sorted(
                classes[vector], key=lambda row: row["a5_pattern_pair"]
            ),
        }
        for vector in basis
    ]
    return {
        "matrix": {
            "sha256": digest_bytes(matrix_data),
            "shape": [54, 35],
            "tree_parent_count": 14,
            "non_tree_parent_count": 21,
            "ranks_over_Q": ranks,
        },
        "blind_block": {
            "row_count": 8,
            "signed_classes_up_to_sign": 4,
            "class_multiplicities": [2, 2, 2, 2],
            "minimum_parent_cover_size": cover_size,
            "minimum_parent_cover_count": len(covers),
            "minimum_parent_covers": [list(cover) for cover in covers],
            "forced_parent": "00115",
            "rows_with_forced_parent_as_unique_channel": forced_rows,
            "forced_a5_children": forced_children,
        },
        "primitive_integral_core": {
            "rank": 4,
            "row_classes": class_rows,
            "unit_minor": {
                "parent_columns": [non_tree_columns[index] for index in chosen],
                "matrix": minor,
                "determinant": det_value,
                "integer_inverse": inverse,
            },
            "determinantal_divisors": divisors,
            "minor_counts_checked_by_size": minor_counts,
            "nonzero_minor_counts_by_size": nonzero_counts,
            "smith_invariant_factors": smith,
            "row_lattice_primitive": True,
        },
        "forced_parent_support": {
            "s5_parent_coordinate": "S5:5:4:00115",
            "directed_arcs": directed_arcs,
            "support_class": s5_metadata["00115"]["support_class"],
        },
    }


def enumerate_conditional_a4(
    payload: dict[str, Any],
) -> tuple[list[tuple[int, ...]], list[str], set[int], list[set[int]]]:
    a4 = payload["groups"]["A4"]
    metadata = [row for row in a4["coordinate_metadata"] if row["degree"] == 3]
    coordinate_ids = [row["coordinate_id"] for row in metadata]
    records = a4["top_degree_pair_by_coordinate_separation_bitsets"]
    require(len(coordinate_ids) == 21, "A4 cubic coordinate count")
    require([row["coordinate_id"] for row in records] == coordinate_ids, "A4 mask order")
    masks = [int(row["separated_pair_mask_hex"], 16) for row in records]
    universe = (1 << a4["residual_pair_count"]) - 1
    for size in range(1, 4):
        for choice in itertools.combinations(range(21), size):
            covered = 0
            for index in choice:
                covered |= masks[index]
            require(covered != universe, "A4 cubic cover below four")
    winners: list[tuple[int, ...]] = []
    for choice in itertools.combinations(range(21), 4):
        covered = 0
        for index in choice:
            covered |= masks[index]
        if covered == universe:
            winners.append(choice)
    require(len(winners) == 128, "A4 conditional solution count")
    lookup = {coordinate: index for index, coordinate in enumerate(coordinate_ids)}
    distributed = [
        tuple(sorted(lookup[value] for value in row["coordinate_ids"]))
        for row in a4["conditional_top_degree_extension"]["solutions"]
    ]
    require(distributed == winners, "A4 conditional solution list")
    tree = {
        index
        for index, row in enumerate(metadata)
        if row["support_class"]["category"] == "TREE_ON_ALL_VERTICES"
    }
    adjacency = [set() for _ in winners]
    solution_sets = [frozenset(solution) for solution in winners]
    for left, right in itertools.combinations(range(128), 2):
        if len(solution_sets[left] ^ solution_sets[right]) == 2:
            adjacency[left].add(right)
            adjacency[right].add(left)
    return winners, coordinate_ids, tree, adjacency


def compose_permutation(left: Sequence[int], right: Sequence[int]) -> tuple[int, ...]:
    return tuple(left[right[index]] for index in range(len(left)))


def verify_cube_action(
    generators: Sequence[Sequence[int]],
    adjacency: Sequence[set[int]],
    tree_counts: Sequence[int],
) -> dict[str, object]:
    size = len(tree_counts)
    identity = tuple(range(size))
    normalized = [tuple(generator) for generator in generators]
    require(len(normalized) == 3, "cube generator count")
    for generator in normalized:
        require(sorted(generator) == list(range(size)), "cube generator is not a permutation")
        require(compose_permutation(generator, generator) == identity, "cube generator is not an involution")
        for left in range(size):
            require(
                {generator[right] for right in adjacency[left]}
                == adjacency[generator[left]],
                "cube generator is not a graph automorphism",
            )
    for left, right in itertools.combinations(normalized, 2):
        require(
            compose_permutation(left, right) == compose_permutation(right, left),
            "cube generators do not commute",
        )
    words: dict[str, tuple[int, ...]] = {}
    for mask in range(8):
        permutation = identity
        for index, generator in enumerate(normalized):
            if mask & (1 << (2 - index)):
                permutation = compose_permutation(generator, permutation)
        words[f"{mask:03b}"] = permutation
    require(len(set(words.values())) == 8, "cube action has order below eight")
    for left in range(8):
        for right in range(8):
            require(
                compose_permutation(words[f"{left:03b}"], words[f"{right:03b}"])
                == words[f"{left ^ right:03b}"],
                "cube group law",
            )
    fixed = {
        word: sum(permutation[index] == index for index in range(size))
        for word, permutation in words.items()
        if word != "000"
    }
    require(all(value == 0 for value in fixed.values()), "cube action is not free")
    unseen = set(range(size))
    orbit_rows = []
    while unseen:
        seed = min(unseen)
        orbit = sorted({permutation[seed] for permutation in words.values()})
        unseen.difference_update(orbit)
        distribution = Counter(tree_counts[index] for index in orbit)
        by_word = {
            word: tree_counts[permutation[seed]]
            for word, permutation in sorted(words.items())
        }
        origins = [
            origin
            for origin in range(8)
            if all(
                by_word[f"{mask:03b}"] == 1 + (mask ^ origin).bit_count()
                for mask in range(8)
            )
        ]
        require(len(origins) == 1, "cube orbit has no unique grading origin")
        orbit_rows.append(
            {
                "seed_solution_index": seed,
                "solution_indices": orbit,
                "grading_origin_word": f"{origins[0]:03b}",
                "tree_count_distribution": {
                    str(key): distribution[key] for key in sorted(distribution)
                },
            }
        )
    require(len(orbit_rows) == 16, "cube orbit count")
    require(all(len(row["solution_indices"]) == 8 for row in orbit_rows), "cube orbit size")
    aggregate = Counter(tree_counts)
    require(aggregate == Counter({1: 16, 2: 48, 3: 48, 4: 16}), "cube grading distribution")
    return {
        "abstract_group": "C2^3",
        "order": 8,
        "free": True,
        "word_permutations": {key: list(value) for key, value in sorted(words.items())},
        "fixed_point_counts_nonidentity": dict(sorted(fixed.items())),
        "orbit_count": 16,
        "orbit_rows": orbit_rows,
        "tree_count_distribution": {
            str(key): aggregate[key] for key in sorted(aggregate)
        },
        "tree_count_polynomial": "16*z*(1+z)^3",
    }


def compute_a4_action(
    payload: dict[str, Any],
    labels_raw: Sequence[Sequence[int]],
    component_phi_raw: Sequence[Sequence[Sequence[int]]],
) -> dict[str, object]:
    winners, coordinate_ids, tree_coordinates, adjacency = enumerate_conditional_a4(payload)
    labels = [tuple(int(value) for value in row) for row in labels_raw]
    require(len(labels) == 128, "A4 factor-label count")
    require(
        set(labels)
        == {
            (component, k4, bits)
            for component in range(4)
            for k4 in range(4)
            for bits in range(8)
        },
        "A4 factor labels are not a bijection",
    )
    for left, right in itertools.combinations(range(128), 2):
        component_left, k_left, bits_left = labels[left]
        component_right, k_right, bits_right = labels[right]
        expected = component_left == component_right and (
            (k_left == k_right and (bits_left ^ bits_right).bit_count() == 1)
            or (bits_left == bits_right and k_left != k_right)
        )
        require((right in adjacency[left]) == expected, "A4 K4 x Q3 factor witness")
    require(Counter(map(len, adjacency)) == Counter({6: 128}), "A4 exchange degree")
    components: list[list[int]] = []
    unseen = set(range(128))
    while unseen:
        seed = min(unseen)
        queue = deque([seed])
        component = {seed}
        unseen.remove(seed)
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    require([len(component) for component in components] == [32] * 4, "A4 component sizes")

    component_phi = [
        [tuple(int(value) for value in permutation) for permutation in row]
        for row in component_phi_raw
    ]
    require(len(component_phi) == 4, "A4 component twist count")
    identity4 = tuple(range(4))
    for row in component_phi:
        require(len(row) == 3, "A4 component twist width")
        for permutation in row:
            require(sorted(permutation) == list(range(4)), "A4 K4 twist permutation")
            require(compose_permutation(permutation, permutation) == identity4, "A4 K4 twist involution")
        for left, right in itertools.combinations(row, 2):
            require(compose_permutation(left, right) == compose_permutation(right, left), "A4 K4 twists do not commute")
    label_lookup = {label: index for index, label in enumerate(labels)}
    generators: list[list[int]] = []
    for generator_index in range(3):
        permutation = []
        for component, k4, bits in labels:
            target = (
                component,
                component_phi[component][generator_index][k4],
                bits ^ (1 << (2 - generator_index)),
            )
            require(target in label_lookup, "A4 action leaves factor carrier")
            permutation.append(label_lookup[target])
        generators.append(permutation)
    tree_counts = [
        sum(coordinate in tree_coordinates for coordinate in solution)
        for solution in winners
    ]
    action = verify_cube_action(generators, adjacency, tree_counts)
    return {
        "carrier": {
            "cubic_coordinate_count": 21,
            "minimum_cover_size": 4,
            "solution_count": 128,
            "coordinate_ids": coordinate_ids,
            "solution_masks_sha256": digest_value(
                [sum(1 << index for index in solution) for solution in winners]
            ),
        },
        "exchange_graph": {
            "adjacency_rule": "symmetric difference has size two",
            "vertex_count": 128,
            "edge_count": sum(map(len, adjacency)) // 2,
            "degree_distribution": {"6": 128},
            "component_count": 4,
            "component_sizes": [32, 32, 32, 32],
            "factorization": "4(K4 CARTESIAN Q3)",
            "factor_labels_by_solution_index": [list(row) for row in labels],
        },
        "component_k4_twists": [
            [list(permutation) for permutation in row] for row in component_phi
        ],
        "generator_solution_permutations": generators,
        "group_action": action,
        "action_boundary": {
            "domain": "the 128 minimum conditional cubic A4 solutions",
            "induced_by_one_global_permutation_of_all_21_coordinates": False,
            "identified_with_transpose_or_odd_relabelling": False,
        },
    }


def group_rows(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = value["groups"]
    require(isinstance(rows, list), "group rows must be a list")
    return {row["group"]: row for row in rows}


def compute_minimum_landscapes(
    payload: dict[str, Any], family: dict[str, Any], instance: dict[str, Any]
) -> dict[str, object]:
    family_rows = group_rows(family)
    instance_rows = group_rows(instance)
    expected = {
        "S4": {"minimum": 7, "quadratics": 5, "cubics": 2, "solutions": 2},
        "A4": {"minimum": 11, "quadratics": 7, "cubics": 4, "solutions": 128},
    }
    result: dict[str, object] = {}
    for name, target in expected.items():
        group = payload["groups"][name]
        structural = family_rows[name]
        minimum_instance = instance_rows[name]
        arithmetic = structural["lower_bound_arithmetic"]
        require(
            arithmetic["block_coordinate_sets_disjoint"] is True
            and arithmetic["forced_degree_one"] == 1
            and arithmetic["quadratic_vertex_cover"] == target["quadratics"] - 1
            and arithmetic["cubic_packing"] == target["cubics"]
            and arithmetic["lower_bound"] == target["minimum"]
            and arithmetic["claimed_minimum"] == target["minimum"],
            f"{name} structural lower-bound arithmetic",
        )
        quadratics = structural["complete_quadratic_graph"]["quadratic_coordinate_ids"]
        require(len(quadratics) == target["quadratics"], f"{name} quadratic count")
        require(structural["complete_quadratic_graph"]["graph"] == f"K{target['quadratics']}", f"{name} complete graph")
        require(structural["forced_degree_one"]["coordinate_ids"] == [f"{name}-D1-C000"], f"{name} forced linear coordinate")
        require(structural["disjoint_cubic_constraints"]["packing_lower_bound"] == target["cubics"], f"{name} cubic packing")
        solutions = group["conditional_top_degree_extension"]["solutions"]
        require(len(solutions) == target["solutions"], f"{name} conditional solution count")
        metadata = group["coordinate_metadata"]
        linear = [row for row in metadata if row["degree"] == 1]
        quadratic = [row for row in metadata if row["degree"] == 2]
        cubic = [row for row in metadata if row["degree"] == 3]
        require(len(linear) == 1 and len(quadratic) == target["quadratics"], f"{name} degree blocks")
        require(len(cubic) == structural["disjoint_cubic_constraints"]["cubic_coordinate_count"], f"{name} cubic block")
        cubic_lookup = {row["coordinate_id"]: index for index, row in enumerate(cubic)}
        tree_indices = {
            index
            for index, row in enumerate(cubic)
            if row["support_class"]["category"] == "TREE_ON_ALL_VERTICES"
        }
        conditional_masks = [
            tuple(sorted(cubic_lookup[value] for value in row["coordinate_ids"]))
            for row in solutions
        ]
        require(all(len(row) == target["cubics"] for row in conditional_masks), f"{name} conditional width")
        tree_distribution = Counter(
            sum(index in tree_indices for index in solution)
            for solution in conditional_masks
        )
        all_coordinate_ids = minimum_instance["coordinate_ids"]
        expected_instance_ids = (
            [f"{name}-D1-C000"]
            + [f"{name}-D2-C{index:03d}" for index in range(len(quadratic))]
            + [f"{name}-D3-C{index:03d}" for index in range(len(cubic))]
        )
        require(
            all_coordinate_ids == expected_instance_ids,
            f"{name} coordinate order",
        )
        distinct_masks = [
            int(row["mask_int"])
            for row in minimum_instance["distinct_separator_masks"]
        ]
        global_masks: list[int] = []
        cubic_offset = 1 + target["quadratics"]
        for omitted in range(target["quadratics"]):
            lower_mask = 1
            for index in range(target["quadratics"]):
                if index != omitted:
                    lower_mask |= 1 << (1 + index)
            for solution in conditional_masks:
                support = lower_mask
                for index in solution:
                    support |= 1 << (cubic_offset + index)
                require(support.bit_count() == target["minimum"], f"{name} global support size")
                require(all(support & constraint for constraint in distinct_masks), f"{name} product support is nonseparating")
                global_masks.append(support)
        require(len(set(global_masks)) == target["quadratics"] * target["solutions"], f"{name} global product duplicates")
        global_tree = {
            str(key): target["quadratics"] * value
            for key, value in sorted(tree_distribution.items())
        }
        result[name] = {
            "global_minimum_size": target["minimum"],
            "global_minimum_count": len(global_masks),
            "degree_profile": [1, target["quadratics"] - 1, target["cubics"]],
            "quadratic_omission_count": target["quadratics"],
            "conditional_cubic_solution_count": target["solutions"],
            "exact_cartesian_product": True,
            "conditional_cubic_tree_count_distribution": {
                str(key): value for key, value in sorted(tree_distribution.items())
            },
            "global_cubic_tree_count_distribution": global_tree,
            "global_solution_masks_sha256": digest_value(sorted(global_masks)),
        }
    require(result["S4"]["global_minimum_count"] == 10, "S4 global landscape count")
    require(result["A4"]["global_minimum_count"] == 896, "A4 global landscape count")
    require(
        result["A4"]["global_cubic_tree_count_distribution"]
        == {"1": 112, "2": 336, "3": 336, "4": 112},
        "A4 global tree-count distribution",
    )
    return result


def compute_global_a4(
    landscapes: dict[str, object], action: dict[str, object]
) -> dict[str, object]:
    require(landscapes["A4"]["exact_cartesian_product"] is True, "A4 product prerequisite")
    exchange = action["exchange_graph"]
    group_action = action["group_action"]
    edge_count = math.comb(7, 2) * 128 + exchange["edge_count"] * 7
    require(edge_count == 5376, "global A4 edge count")
    return {
        "adjacency_rule": "symmetric difference has size two",
        "vertex_count": 896,
        "edge_count": edge_count,
        "degree_distribution": {"12": 896},
        "component_count": 4,
        "component_sizes": [224, 224, 224, 224],
        "factorization": "4(K7 CARTESIAN K4 CARTESIAN Q3)",
        "factorization_is_explicit_via_certificate_labels": True,
        "extended_c2_cube_action": {
            "order": group_action["order"],
            "free": group_action["free"],
            "acts_trivially_on_k7_factor": True,
            "orbit_count": 7 * group_action["orbit_count"],
            "orbit_size": 8,
            "tree_count_distribution": landscapes["A4"]["global_cubic_tree_count_distribution"],
            "tree_count_polynomial": "112*z*(1+z)^3",
        },
    }


def build_certificate(
    payload: dict[str, Any],
    family: dict[str, Any],
    instance: dict[str, Any],
    matrix_data: bytes,
    labels: Sequence[Sequence[int]],
    component_phi: Sequence[Sequence[Sequence[int]]],
) -> dict[str, object]:
    landscapes = compute_minimum_landscapes(payload, family, instance)
    a5 = compute_a5(payload, matrix_data)
    a4 = compute_a4_action(payload, labels, component_phi)
    global_a4 = compute_global_a4(landscapes, a4)
    return {
        "schema_version": "orbit_sum_structural_certificate_v1",
        "scope": {
            "n_values": [4, 5],
            "actions": ["S4", "A4", "S5", "A5"],
            "carrier": "Boolean loopless directed graphs",
            "coordinate_dictionary": "cumulative squarefree support-orbit sums",
        },
        "minimum_landscapes": landscapes,
        "a5_signed_blind_core": a5,
        "a4_exchange_action": a4,
        "a4_global_exchange_graph": global_a4,
        "interpretive_limits": {
            "a5_parent_cover_two_is_not_global_minimum_seventeen": True,
            "a4_action_is_on_solution_sets_not_the_coordinate_carrier": True,
            "no_statement_for_n_greater_than_five": True,
            "no_physical_or_chemical_interpretation": True,
            "no_novelty_priority_or_firstness_claim": True,
        },
    }


def verify(root: Path, reconstructed_matrix: Path | None = None) -> dict[str, object]:
    structural = root / "certificates" / "structural"
    payload = load_json(root / "certificates" / "five_vertex" / "canonical_payload.json")
    family = load_json(
        root
        / "certificates"
        / "family_degree"
        / "structural"
        / "finite_theorem_certificate.json"
    )
    instance = load_json(
        root
        / "certificates"
        / "minimum_fingerprints"
        / "primary"
        / "instance.json"
    )
    matrix_path = structural / "a5_signed_matrix.csv"
    matrix_data = matrix_path.read_bytes()
    if reconstructed_matrix is not None:
        require(
            reconstructed_matrix.read_bytes() == matrix_data,
            "independently reconstructed A5 signed matrix differs",
        )
    certificate_path = structural / "structural_certificate.json"
    raw = certificate_path.read_bytes()
    certificate = load_json(certificate_path)
    require(raw == canonical_json_bytes(certificate), "structural certificate is not canonical JSON")
    a4 = certificate.get("a4_exchange_action")
    require(isinstance(a4, dict), "missing A4 action certificate")
    exchange = a4.get("exchange_graph")
    require(isinstance(exchange, dict), "missing A4 exchange witness")
    labels = exchange.get("factor_labels_by_solution_index")
    phi = a4.get("component_k4_twists")
    require(isinstance(labels, list) and isinstance(phi, list), "missing A4 factor witnesses")
    expected = build_certificate(payload, family, instance, matrix_data, labels, phi)
    require(certificate == expected, "structural certificate semantic drift")
    return {
        "certificate_sha256": digest_bytes(raw),
        "matrix_sha256": digest_bytes(matrix_data),
        "minimum_counts": [
            expected["minimum_landscapes"]["S4"]["global_minimum_count"],
            expected["minimum_landscapes"]["A4"]["global_minimum_count"],
        ],
        "a5_blind_rank": expected["a5_signed_blind_core"]["primitive_integral_core"]["rank"],
        "a4_global_vertices": expected["a4_global_exchange_graph"]["vertex_count"],
        "a4_global_edges": expected["a4_global_exchange_graph"]["edge_count"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--reconstructed-matrix", type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = verify(args.root.resolve(), args.reconstructed_matrix)
    except (OSError, KeyError, TypeError, ValueError, StructuralCertificateError) as error:
        print(f"STRUCTURAL_CERTIFICATE_FAIL|{type(error).__name__}|{error}", file=sys.stderr)
        return 1
    print(
        "PASS_STRUCTURAL_CERTIFICATES"
        f"|counts={result['minimum_counts'][0]},{result['minimum_counts'][1]}"
        f"|blind_rank={result['a5_blind_rank']}"
        f"|global_A4={result['a4_global_vertices']},{result['a4_global_edges']}"
        f"|certificate_sha256={result['certificate_sha256']}"
        f"|matrix_sha256={result['matrix_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
