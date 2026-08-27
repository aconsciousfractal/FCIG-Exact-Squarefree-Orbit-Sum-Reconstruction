from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import verify  # noqa: E402
import build_manifest  # noqa: E402


def git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    return result.stdout


@contextmanager
def committed_repository(files: dict[str, str]):
    with tempfile.TemporaryDirectory(prefix="orbit_sum_git_boundary_") as raw:
        repo = Path(raw)
        git(repo, "init", "-q", "-b", "main")
        for relative, text in files.items():
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        git(repo, "add", "-A")
        git(
            repo,
            "-c",
            "user.name=Boundary Test",
            "-c",
            "user.email=boundary@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        )
        with mock.patch.object(verify, "ROOT", repo), mock.patch.object(build_manifest, "ROOT", repo):
            yield repo


class GitBoundaryPortabilityTests(unittest.TestCase):
    def test_plain_repository_without_remote_or_lfs_installation(self) -> None:
        with committed_repository({"payload.txt": "ordinary blob\n"}):
            result = verify.verify_git_boundary(False)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["lfs_pointers"], 0)

    def test_plain_repository_with_remote(self) -> None:
        with committed_repository({"payload.txt": "ordinary blob\n"}) as repo:
            git(repo, "remote", "add", "origin", "https://example.invalid/repository.git")
            self.assertEqual(verify.verify_git_boundary(False)["status"], "PASS")

    def test_standard_clone_with_remote_tracking_refs(self) -> None:
        with committed_repository(
            {
                ".gitattributes": "* text=auto eol=lf\n",
                "payload.txt": "ordinary blob\n",
            }
        ) as source:
            with tempfile.TemporaryDirectory(prefix="orbit_sum_git_clone_") as raw:
                clone = Path(raw) / "clone"
                subprocess.run(["git", "clone", "-q", str(source), str(clone)], check=True, capture_output=True)
                with mock.patch.object(verify, "ROOT", clone), mock.patch.object(build_manifest, "ROOT", clone):
                    result = verify.verify_git_boundary(False)
                    self.assertEqual(result["reachable_commits"], 1)
                    self.assertGreaterEqual(result["reachable_refs"], 2)

    def test_development_state_accepts_ordinary_second_commit(self) -> None:
        with committed_repository({"payload.txt": "ordinary blob\n"}) as repo:
            (repo / "payload.txt").write_text("second commit\n", encoding="utf-8", newline="\n")
            git(repo, "add", "payload.txt")
            git(repo, "-c", "user.name=Boundary Test", "-c", "user.email=boundary@example.invalid", "commit", "-q", "-m", "second")
            result = verify.verify_git_boundary(False, "development")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["reachable_commits"], 2)

    def test_tag_is_rejected_before_release(self) -> None:
        with committed_repository({"payload.txt": "ordinary blob\n"}) as repo:
            git(repo, "tag", "v2.1.0")
            with self.assertRaisesRegex(ValueError, "candidate checkout already contains"):
                verify.verify_git_boundary(False, "candidate")

    def test_release_requires_the_declared_tag(self) -> None:
        with committed_repository({"payload.txt": "ordinary blob\n"}):
            with self.assertRaisesRegex(ValueError, "release checkout is missing"):
                verify.verify_git_boundary(False, "release")

    def test_release_accepts_annotated_tag_on_same_head(self) -> None:
        with committed_repository({"payload.txt": "ordinary blob\n"}) as repo:
            git(
                repo,
                "-c",
                "user.name=Boundary Test",
                "-c",
                "user.email=boundary@example.invalid",
                "tag",
                "-a",
                "v2.1.0",
                "-m",
                "release",
            )
            result = verify.verify_git_boundary(False, "release")
            self.assertTrue(result["release_tag_present"])
            self.assertEqual(result["release_tag_target"], git(repo, "rev-parse", "HEAD").strip())
            self.assertEqual(result["release_tag_kind"], "tag")

    def test_release_rejects_lightweight_tag(self) -> None:
        with committed_repository({"payload.txt": "ordinary blob\n"}) as repo:
            git(repo, "tag", "v2.1.0")
            with self.assertRaisesRegex(ValueError, "must be an annotated tag"):
                verify.verify_git_boundary(False, "release")

    def test_release_rejects_tag_on_an_ancestor(self) -> None:
        with committed_repository({"payload.txt": "ordinary blob\n"}) as repo:
            root = git(repo, "rev-parse", "HEAD").strip()
            git(
                repo,
                "-c",
                "user.name=Boundary Test",
                "-c",
                "user.email=boundary@example.invalid",
                "tag",
                "-a",
                "v2.1.0",
                root,
                "-m",
                "release",
            )
            (repo / "payload.txt").write_text("second commit\n", encoding="utf-8", newline="\n")
            git(repo, "add", "payload.txt")
            git(repo, "-c", "user.name=Boundary Test", "-c", "user.email=boundary@example.invalid", "commit", "-q", "-m", "second")
            with self.assertRaisesRegex(ValueError, "does not point to HEAD"):
                verify.verify_git_boundary(False, "release")

    def test_governance_path_in_root_tree_is_rejected(self) -> None:
        private_path = "experiments/" + "P" + "58_secret/receipt.json"
        with committed_repository({"payload.txt": "ordinary blob\n", private_path: "{}\n"}):
            with self.assertRaisesRegex(ValueError, "historical governance paths"):
                verify.verify_git_boundary(False)

    def test_development_state_allows_divergent_remote_tracking_ref(self) -> None:
        with committed_repository({"payload.txt": "ordinary blob\n"}) as repo:
            root = git(repo, "rev-parse", "HEAD").strip()
            (repo / "payload.txt").write_text("second commit\n", encoding="utf-8", newline="\n")
            git(repo, "add", "payload.txt")
            git(repo, "-c", "user.name=Boundary Test", "-c", "user.email=boundary@example.invalid", "commit", "-q", "-m", "second")
            git(repo, "update-ref", "refs/remotes/origin/legacy", root)
            result = verify.verify_git_boundary(False, "development")
            self.assertEqual(result["status"], "PASS")

    def test_any_tracked_filter_is_rejected_without_parsing_git_lfs_status(self) -> None:
        with committed_repository(
            {
                ".gitattributes": "payload.bin filter=lfs diff=lfs merge=lfs -text\n",
                "payload.bin": "ordinary blob that should never be filtered\n",
            }
        ):
            with self.assertRaisesRegex(ValueError, "Git filter"):
                verify.verify_git_boundary(False)

    def test_lfs_pointer_payload_is_rejected_even_without_filter_attribute(self) -> None:
        pointer = (
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
            "size 123\n"
        )
        with committed_repository({"payload.bin": pointer}):
            with self.assertRaisesRegex(ValueError, "Git LFS pointers"):
                verify.verify_git_boundary(False)

    def test_every_manifest_exclusion_is_rejected_if_tracked(self) -> None:
        excluded = (
            "tmp/hidden.md",
            "nested/__pycache__/hidden.py",
            "nested/.pytest_cache/hidden.txt",
            "tmp/package_verification.json",
            "paper/main.aux",
            "paper/main.bbl",
            "paper/main.blg",
            "paper/main.fdb_latexmk",
            "paper/main.fls",
            "paper/main.log",
            "paper/main.out",
            "paper/main.toc",
            "scripts/hidden.pyc",
        )
        for relative in excluded:
            with self.subTest(relative=relative):
                with committed_repository({"payload.txt": "ordinary blob\n", relative: "unmanifested claim\n"}):
                    with self.assertRaisesRegex(ValueError, "escapes manifest boundary"):
                        verify.verify_git_boundary(False)

    def test_assume_unchanged_cannot_hide_worktree_bytes(self) -> None:
        with committed_repository({"payload.txt": "governed original\n"}) as repo:
            (repo / "payload.txt").write_text("false public claim\n", encoding="utf-8", newline="\n")
            git(repo, "update-index", "--assume-unchanged", "payload.txt")
            with self.assertRaisesRegex(ValueError, "nonstandard Git index flags"):
                verify.verify_git_boundary(False)

    def test_skip_worktree_cannot_hide_worktree_bytes(self) -> None:
        with committed_repository({"payload.txt": "governed original\n"}) as repo:
            git(repo, "update-index", "--skip-worktree", "payload.txt")
            (repo / "payload.txt").write_text("false public claim\n", encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(ValueError, "nonstandard Git index flags"):
                verify.verify_git_boundary(False)

    def test_symlink_mode_is_rejected_from_the_index(self) -> None:
        with committed_repository({"payload.txt": "target\n"}) as repo:
            oid = git(repo, "rev-parse", "HEAD:payload.txt").strip()
            git(repo, "update-index", "--add", "--cacheinfo", f"120000,{oid},link")
            with self.assertRaisesRegex(ValueError, "non-regular tracked mode 120000"):
                verify.verify_git_boundary(False)


if __name__ == "__main__":
    unittest.main()
