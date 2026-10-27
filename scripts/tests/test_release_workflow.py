"""Run the actual release workflow's shell steps against isolated Git fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/release.yml"


def shell_step(name, workflow=WORKFLOW):
    lines = workflow.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"- name: {name}")
    start = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |") + 1
    body = []
    for line in lines[start:]:
        if line and not line.startswith("          "):
            break
        body.append(line[10:] if line else "")
    return "\n".join(body)


class ReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.email", "release-test@example.invalid")
        self.git("config", "user.name", "Release Test")
        (self.repo / "README.md").write_text("Release test\n")
        self.git("add", ".")
        self.git("commit", "-qm", "main commit")
        self.origin = self.root / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True)
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-q", "origin", "main")
        self.env = dict(os.environ, GITHUB_REF_NAME="v1.0.0")
        self.calls = self.root / "gh-calls.jsonl"
        fakebin = self.root / "bin"
        fakebin.mkdir()
        gh = fakebin / "gh"
        gh.write_text(f"#!{sys.executable}\n" + """
import json, os, sys
with open(os.environ['RELEASE_TEST_CALLS'], 'a') as out:
    out.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1:3] == ['release', 'view']:
    sys.exit(0 if os.environ.get('RELEASE_TEST_EXISTS') else 1)
""")
        gh.chmod(0o755)
        self.env.update(PATH=str(fakebin) + os.pathsep + self.env["PATH"], RELEASE_TEST_CALLS=str(self.calls))

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True, stderr=subprocess.PIPE)

    def step(self, name):
        return subprocess.run(
            ["bash", "-c", shell_step(name)], cwd=self.repo, env=self.env, capture_output=True, text=True,
        )

    def test_accepts_exact_semantic_versions(self):
        for tag in ("v1.0.0", "v0.2.10", "v12.34.56"):
            with self.subTest(tag=tag):
                self.env["GITHUB_REF_NAME"] = tag
                self.assertEqual(self.step("Validate semantic version").returncode, 0)

    def test_refuses_malformed_and_prerelease_tags(self):
        for tag in ("v1.0", "v1.0.0-rc.1", "v01.0.0", "v1.0.0.4", "1.0.0", "v1.0.0;echo bad"):
            with self.subTest(tag=tag):
                self.env["GITHUB_REF_NAME"] = tag
                self.assertNotEqual(self.step("Validate semantic version").returncode, 0)

    def test_accepts_annotated_tag_on_main(self):
        self.git("tag", "-a", "v1.0.0", "-m", "v1.0.0")
        result = self.step("Verify release commit belongs to main")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_refuses_tag_from_unmerged_branch(self):
        self.git("switch", "-c", "unmerged")
        (self.repo / "README.md").write_text("unmerged release\n")
        self.git("add", ".")
        self.git("commit", "-qm", "unmerged commit")
        self.git("tag", "-a", "v1.0.0", "-m", "v1.0.0")
        self.assertNotEqual(self.step("Verify release commit belongs to main").returncode, 0)

    def test_refuses_checkout_different_from_tagged_commit(self):
        self.git("tag", "-a", "v1.0.0", "-m", "v1.0.0")
        (self.repo / "README.md").write_text("a newer checkout\n")
        self.git("add", ".")
        self.git("commit", "-qm", "newer commit")
        self.assertNotEqual(self.step("Verify release commit belongs to main").returncode, 0)

    def test_existing_release_is_never_overwritten(self):
        self.env["RELEASE_TEST_EXISTS"] = "1"
        result = self.step("Create GitHub Release")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertFalse(any(call[:2] == ["release", "create"] for call in calls))

    def test_new_release_verifies_tag_and_generates_notes(self):
        result = self.step("Create GitHub Release")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        created = next(call for call in calls if call[:2] == ["release", "create"])
        self.assertEqual(created[2], "v1.0.0")
        self.assertIn("--verify-tag", created)
        self.assertIn("--generate-notes", created)
        self.assertNotIn("--clobber", created)


if __name__ == "__main__":
    unittest.main()
