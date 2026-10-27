"""Exercise release selection and registry rerun handling from the real workflow."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_release_workflow import shell_step


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/packages.yml"


class PackageWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.email", "packages-test@example.invalid")
        self.git("config", "user.name", "Packages Test")
        (self.repo / "README.md").write_text("release\n")
        self.git("add", ".")
        self.git("commit", "-qm", "release")
        self.git("tag", "-a", "v1.0.0", "-m", "v1.0.0")
        self.sha = self.git("rev-parse", "HEAD").strip()
        origin = self.root / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        self.git("remote", "add", "origin", str(origin))
        self.git("push", "-q", "origin", "main", "v1.0.0")
        self.output = self.root / "output"
        self.env = dict(
            os.environ, INPUT_TAG="", GITHUB_REF_NAME="v1.0.0",
            GITHUB_REPOSITORY="ExampleOwner/ExampleRepo", GITHUB_OUTPUT=str(self.output),
            RUNNER_TEMP=str(self.root), IMAGE="ghcr.io/example/image:v1.0.0",
        )

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True, stderr=subprocess.PIPE)

    def step(self, name):
        return subprocess.run(
            ["bash", "-c", shell_step(name, WORKFLOW)], cwd=self.repo,
            env=self.env, capture_output=True, text=True,
        )

    def test_tag_push_selects_release_sha_and_lowercase_image_path(self):
        result = self.step("Resolve release tag")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(),
                         f"sha={self.sha}\ntag=v1.0.0\nimage_base=ghcr.io/exampleowner/examplerepo\n")

    def test_manual_backfill_selects_tag_instead_of_current_main(self):
        (self.repo / "README.md").write_text("newer main\n")
        self.git("commit", "-qam", "newer main")
        self.git("push", "-q", "origin", "main")
        self.env.update(INPUT_TAG="v1.0.0", GITHUB_REF_NAME="main")
        result = self.step("Resolve release tag")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"sha={self.sha}\n", self.output.read_text())

    def test_invalid_tags_are_refused_before_git_fetch(self):
        for tag in ("main", "v01.0.0", "v1.0.0-rc.1", "v1.0.0;touch injected"):
            with self.subTest(tag=tag):
                self.env["INPUT_TAG"] = tag
                self.assertNotEqual(self.step("Resolve release tag").returncode, 0)
                self.assertFalse(self.output.exists())
        self.assertFalse((self.repo / "injected").exists())

    def test_missing_tag_is_refused(self):
        self.env["INPUT_TAG"] = "v9.9.9"
        self.assertNotEqual(self.step("Resolve release tag").returncode, 0)
        self.assertFalse(self.output.exists())

    def test_unmerged_release_is_refused(self):
        self.git("switch", "-c", "unmerged")
        (self.repo / "README.md").write_text("unmerged\n")
        self.git("commit", "-qam", "unmerged")
        self.git("tag", "v2.0.0")
        self.git("push", "-q", "origin", "v2.0.0")
        self.env["INPUT_TAG"] = "v2.0.0"
        self.assertNotEqual(self.step("Resolve release tag").returncode, 0)
        self.assertFalse(self.output.exists())

    def test_registry_errors_are_not_mistaken_for_missing_images(self):
        fakebin = self.root / "bin"
        fakebin.mkdir()
        docker = fakebin / "docker"
        docker.write_text('#!/bin/sh\nprintf "%s\\n" "$REGISTRY_ERROR" >&2\nexit "$REGISTRY_STATUS"\n')
        docker.chmod(0o755)
        self.env["PATH"] = str(fakebin) + os.pathsep + self.env["PATH"]
        for status, error, expected in (
            ("0", "", "exists=true\n"),
            ("1", "manifest unknown", "exists=false\n"),
            ("1", "unexpected status: 401 Unauthorized", None),
            ("1", "network timeout", None),
        ):
            with self.subTest(error=error):
                self.output.unlink(missing_ok=True)
                self.env.update(REGISTRY_STATUS=status, REGISTRY_ERROR=error)
                result = self.step("Preserve existing version images")
                if expected:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.output.read_text(), expected)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
