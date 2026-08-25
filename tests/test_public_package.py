from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_manifest  # noqa: E402
import verify  # noqa: E402


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PublicPackageTests(unittest.TestCase):
    def test_headline_tuple(self) -> None:
        payload = load(ROOT / "certificates" / "five_vertex" / "canonical_payload.json")
        groups = payload["groups"]
        order = ("S4", "A4", "S5", "A5")
        self.assertEqual(
            [groups[group]["pattern_orbit_count"] for group in order],
            [218, 368, 9608, 17824],
        )
        self.assertEqual(
            [groups[group]["coordinate_profile_degrees_1_to_top"] for group in order],
            [[1, 5, 13], [1, 7, 21], [1, 5, 16, 61], [1, 6, 21, 96]],
        )
        summary = load(ROOT / "certificates" / "theorem_summary.json")
        self.assertEqual([summary["cases"][group]["global_minimum"] for group in order], [7, 11, 14, 17])

    def test_four_vertex_minima_and_lower_dags(self) -> None:
        rows = verify.group_rows(load(verify.MINIMUM / "primary" / "minimum_fingerprints.json"))
        lower = verify.group_rows(load(verify.MINIMUM / "primary" / "lower_bound_certificate.json"))
        self.assertEqual((rows["S4"]["minimum_size"], rows["A4"]["minimum_size"]), (7, 11))
        self.assertEqual((lower["S4"]["proof_node_count"], lower["A4"]["proof_node_count"]), (11, 22))

    def test_tree_and_conditional_rows(self) -> None:
        groups = load(ROOT / "certificates" / "five_vertex" / "canonical_payload.json")["groups"]
        order = ("S4", "A4", "S5", "A5")
        self.assertEqual([groups[group]["pairs_with_a_tree_separator"] for group in order], [39, 51, 190, 105])
        self.assertEqual(groups["A5"]["tree_blind_pair_count"], 8)
        self.assertTrue(groups["A5"]["all_tree_blind_pairs_are_index_two_split_pairs"])
        self.assertEqual(
            [
                (
                    groups[group]["conditional_top_degree_extension"]["minimum"],
                    groups[group]["conditional_top_degree_extension"]["solution_count_before_external_quotient"],
                )
                for group in order
            ],
            [(2, 2), (4, 128), (4, 2), (4, 200)],
        )

    def test_independent_five_vertex_code_and_payloads(self) -> None:
        producer = ROOT / "scripts" / "five_vertex" / "producer" / "main.py"
        checker = ROOT / "scripts" / "five_vertex" / "checker" / "reconstruct.py"
        self.assertNotEqual(digest(producer), digest(checker))
        self.assertNotIn("import producer", checker.read_text(encoding="utf-8"))
        self.assertEqual(
            digest(ROOT / "certificates" / "five_vertex" / "canonical_payload.json"),
            digest(ROOT / "certificates" / "five_vertex" / "independent" / "reconstructed_payload.json"),
        )

    def test_public_tree_has_no_project_governance_labels(self) -> None:
        suffixes = {".md", ".tex", ".sty", ".bib", ".py", ".json", ".yaml", ".yml", ".cff", ".txt"}
        text = "\n".join(
            path.read_text(encoding="utf-8", errors="strict")
            for path in build_manifest.package_files()
            if path.suffix.lower() in suffixes
        ).upper()
        forbidden = (
            "P" + "58",
            "G" + "8U",
            "INTERNAL" + " DRAFT",
            "NOT FOR" + " CIRCULATION",
            "CANDIDATE" + "_ATTESTATION",
        )
        for token in forbidden:
            self.assertNotIn(token, text)
        self.assertNotIn("COMBINATORIALLY_" + "CHIRAL", text)
        for old_root in ("outputs", "experiments", "g" + "8u1"):
            self.assertFalse((ROOT / old_root).exists())

    def test_build_attestation_records_only_build_facts(self) -> None:
        cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        self.assertIn('version: "2.0.0"', cff)
        self.assertNotIn("date-released:", cff)
        attestation = load(ROOT / "BUILD_ATTESTATION.json")
        self.assertEqual(attestation["version"], "2.0.0")
        self.assertEqual(attestation["intended_release_tag"], "v2.0.0")
        self.assertFalse(attestation["event_boundary"]["external_review_state_recorded"])
        self.assertFalse(attestation["event_boundary"]["publication_state_recorded"])
        self.assertEqual(attestation["pdf_visual_qa"]["status"], "PASS_ALL_PAGES_INSPECTED")
        self.assertEqual(attestation["pdf_visual_qa"]["inspected_pages"], 21)
        self.assertEqual(attestation["pdf_build_toolchain"]["loaded_file_count"], 104)
        self.assertNotIn("review", attestation)
        self.assertNotIn("publication_actions", attestation)
        self.assertNotIn("git_candidate", attestation)

    def test_manifest_excludes_self_reference(self) -> None:
        paths = {build_manifest.relative_name(path) for path in build_manifest.package_files()}
        self.assertNotIn("MANIFEST_SHA256.txt", paths)
        self.assertNotIn("BUILD_ATTESTATION.json", paths)
        self.assertIn("PDF_BUILD_TOOLCHAIN.json", paths)
        self.assertIn("docs/PDF_VISUAL_QA.json", paths)

    def test_unit_tests_are_direct_release_boundary_checks(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
        core = workflow.split("  release-boundary:", 1)[0]
        release = workflow.split("  release-boundary:", 1)[1].split("  full-replay:", 1)[0]
        for name, section in (("core", core), ("release", release)):
            with self.subTest(job=name):
                self.assertIn("python -B -m unittest discover -s tests -v", section)
                self.assertIn("python -B -O -m unittest discover -s tests -v", section)
                self.assertIn("scripts/verify.py --profile core", section)
        self.assertNotIn("apt-get", workflow)
        self.assertNotIn("--profile full", workflow)

    def test_plain_paper_title_block(self) -> None:
        source = (ROOT / "paper" / "main.tex").read_text(encoding="utf-8")
        self.assertIn(r"\date{}", source)
        self.assertNotIn(r"\begin{titlepage}", source)
        self.assertNotIn("fancyhdr", source)

    def test_no_third_party_full_text_and_one_pdf(self) -> None:
        forbidden = {".eprint", ".doc", ".docx", ".rtf", ".epub"}
        self.assertEqual([path for path in ROOT.rglob("*") if path.is_file() and path.suffix.lower() in forbidden], [])
        pdfs = verify.distributed_pdf_paths(ROOT)
        expected = "paper/Exact_Squarefree_Orbit_Sum_Reconstruction_of_Four_and_Five_Vertex_Loopless_Digraphs.pdf"
        self.assertEqual(pdfs, [expected])


if __name__ == "__main__":
    unittest.main()
