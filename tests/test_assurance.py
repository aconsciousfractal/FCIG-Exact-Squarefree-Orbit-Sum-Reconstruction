from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_paper  # noqa: E402
import verify  # noqa: E402


SURFACE_NAMES = (
    "README.md",
    "docs/CLAIM_LEDGER.md",
    "docs/PUBLIC_CLAIM_BOUNDARY.md",
    "paper/sections/01_introduction.tex",
    "paper/tables/T01_exact_panel.tex",
    "paper/sections/04_n4.tex",
    "paper/sections/05_n5.tex",
    "paper/sections/06_tree_index_two.tex",
    "paper/sections/07_conditional.tex",
)


class AssuranceTests(unittest.TestCase):
    def test_pdf_discovery_uses_paths_relative_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orbit_sum_pdf_paths_") as raw:
            root = Path(raw) / "tmp" / "project"
            paper = root / "paper" / "paper.pdf"
            ignored = root / "tmp" / "scratch.pdf"
            paper.parent.mkdir(parents=True)
            ignored.parent.mkdir(parents=True)
            paper.write_bytes(b"%PDF-governed")
            ignored.write_bytes(b"%PDF-scratch")
            self.assertEqual(verify.distributed_pdf_paths(root), ["paper/paper.pdf"])

    def test_windows_extended_path_adapter_is_idempotent(self) -> None:
        candidate = Path("C" + ":" + r"\long-root") if os.name == "nt" else Path("/tmp/long-root")
        once = verify.windows_extended_path(candidate)
        twice = verify.windows_extended_path(once)
        self.assertEqual(str(once), str(twice))
        self.assertEqual(verify.comparable_path(candidate), verify.comparable_path(once))
        if os.name == "nt":
            self.assertTrue(str(once).startswith("\\\\?\\"))

    def test_five_vertex_replay_has_no_fixed_path_length_rejection(self) -> None:
        governed = (
            ROOT / "scripts" / "five_vertex" / "producer" / "main.py",
            ROOT / "scripts" / "five_vertex" / "checker" / "reconstruct.py",
            ROOT / "scripts" / "five_vertex" / "checker" / "verify_lower_bounds.py",
        )
        for path in governed:
            with self.subTest(path=path.name):
                self.assertNotIn("path too long", path.read_text(encoding="utf-8").lower())

    def test_lower_bound_checker_loads_its_sibling_by_exact_path(self) -> None:
        source = (
            ROOT / "scripts" / "five_vertex" / "checker" / "verify_lower_bounds.py"
        ).read_text(encoding="utf-8")
        self.assertIn("spec_from_file_location", source)
        self.assertNotIn("import reconstruct as independent", source)

    def test_direct_latex_tools_precede_latexmk_wrapper(self) -> None:
        tools = {
            "tectonic": None,
            "pdflatex": "mock-pdflatex",
            "bibtex": "mock-bibtex",
            "latexmk": "mock-latexmk",
        }
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            build_paper.shutil, "which", side_effect=lambda name: tools.get(name)
        ):
            commands, compiler = build_paper.compiler_commands(Path("stage"))
        self.assertEqual(compiler, "pdflatex+bibtex")
        self.assertEqual(commands[0][0], tools["pdflatex"])
        self.assertEqual(commands[1], [tools["bibtex"], "main"])
        self.assertEqual(len(commands), 4)

    def test_latexmk_is_only_a_last_resort(self) -> None:
        tools = {"tectonic": None, "pdflatex": None, "bibtex": None, "latexmk": "mock-latexmk"}
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            build_paper.shutil, "which", side_effect=lambda name: tools.get(name)
        ):
            commands, compiler = build_paper.compiler_commands(Path("stage"))
        self.assertEqual(compiler, "latexmk")
        self.assertEqual(commands[0][0], tools["latexmk"])

    def test_build_attestation_is_closed_and_event_free(self) -> None:
        manifest = {"file_count": 100, "sha256": "a" * 64}
        paper = {"bytes": 450000, "pages": 20, "sha256": "b" * 64}
        baseline = verify.expected_attestation(manifest, paper)
        verify.validate_attestation_payload(baseline, manifest, paper)
        mutations = (
            ("version", lambda value: value.__setitem__("version", "2.0.1")),
            ("tag", lambda value: value.__setitem__("intended_release_tag", "v2.0.1")),
            ("external review event", lambda value: value["event_boundary"].__setitem__("external_review_state_recorded", True)),
            ("publication event", lambda value: value["event_boundary"].__setitem__("publication_state_recorded", True)),
            ("novelty", lambda value: value["claim_contract"].__setitem__("novelty_priority_firstness_claimed", True)),
            ("third-party files", lambda value: value["claim_contract"].__setitem__("third_party_full_texts_distributed", 1)),
            ("scope", lambda value: value["mathematical_scope"].__setitem__("n_values", [4, 5, 6])),
            ("unknown key", lambda value: value.__setitem__("unreviewed_claim", "PASS")),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                changed = copy.deepcopy(baseline)
                mutate(changed)
                with self.assertRaisesRegex(ValueError, "attestation schema/value drift"):
                    verify.validate_attestation_payload(changed, manifest, paper)

    def test_strict_json_rejects_duplicate_keys(self) -> None:
        mutations = (
            b'{"novelty":true,"novelty":false}',
            b'{"event_boundary":{"external_review_state_recorded":true,"external_review_state_recorded":false}}',
            b'{"event_boundary":{"publication_state_recorded":true,"publication_state_recorded":false}}',
            b'{"mathematical_scope":{"n_values":[4,5,6],"n_values":[4,5]}}',
        )
        for raw in mutations:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                    verify.parse_strict_json_object(raw, "mutation")

    def test_distributed_build_attestation_is_pretty_canonical_json(self) -> None:
        raw = (ROOT / "BUILD_ATTESTATION.json").read_bytes()
        value = verify.parse_strict_json_object(raw, "BUILD_ATTESTATION.json")
        self.assertEqual(raw, verify.pretty_canonical_json_bytes(value))

    def test_theorem_summary_rejects_headline_mutations(self) -> None:
        baseline = verify.expected_theorem_summary()
        verify.validate_theorem_summary_payload(baseline)
        mutations = (
            ("S4", "reconstruction_degree", 4),
            ("A4", "dictionary_size", 30),
            ("S5", "global_minimum", 15),
            ("A5", "global_minimum", 18),
            ("A5", "residual_pairs_before_top_degree", 114),
            ("S5", "lower_dag_nodes", 63588),
        )
        for group, field, replacement in mutations:
            with self.subTest(group=group, field=field):
                changed = copy.deepcopy(baseline)
                changed["cases"][group][field] = replacement
                with self.assertRaisesRegex(ValueError, "theorem summary schema/value drift"):
                    verify.validate_theorem_summary_payload(changed)

    def test_tex_theorem_mutation_is_rejected(self) -> None:
        summary = verify.expected_theorem_summary()
        surfaces = {name: (ROOT / name).read_text(encoding="utf-8") for name in SURFACE_NAMES}
        verify.validate_textual_summary_surfaces(summary, surfaces)
        surfaces["paper/sections/01_introduction.tex"] = surfaces["paper/sections/01_introduction.tex"].replace(
            "7,11,14,17", "7,11,14,18", 1
        )
        with self.assertRaisesRegex(ValueError, "theorem summary mismatch"):
            verify.validate_textual_summary_surfaces(summary, surfaces)

    def test_positive_scope_widening_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive claim exceeds"):
            verify.validate_scope_ceiling_texts({"mutation": "The theorem holds for all n>5."})

    def test_false_additive_headline_tuple_is_rejected(self) -> None:
        verify.validate_public_four_tuples({"baseline": "The exact global minima are 7,11,14,17."})
        with self.assertRaisesRegex(ValueError, "undeclared public four-tuple"):
            verify.validate_public_four_tuples({"mutation": "The minima are 7,11,14,18."})

    def test_pdf_theorem_mutation_is_rejected(self) -> None:
        summary = verify.expected_theorem_summary()
        pdf = ROOT / "paper" / "Exact_Squarefree_Orbit_Sum_Reconstruction_of_Four_and_Five_Vertex_Loopless_Digraphs.pdf"
        pages = [page.extract_text() or "" for page in PdfReader(str(pdf)).pages]
        verify.validate_pdf_summary(summary, pages)
        changed = [page.replace("7,11,14,17", "7,11,14,18") for page in pages]
        with self.assertRaisesRegex(ValueError, "PDF theorem tuple mismatch"):
            verify.validate_pdf_summary(summary, changed)

    def test_distributed_summary_is_canonical_and_exact(self) -> None:
        raw = (ROOT / "certificates" / "theorem_summary.json").read_bytes()
        value = json.loads(raw)
        self.assertEqual(raw, verify.pretty_canonical_json_bytes(value))
        verify.validate_theorem_summary_payload(value)


if __name__ == "__main__":
    unittest.main()
