"""Exercise deployment safeguards with real Git repos and fake Docker/HTTP tools.

Run: python3 -m unittest discover -s scripts/tests -v
No networked repository changes or real containers/volumes are used.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy_ec2.sh"


class DeploymentSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.origin = self.root / "origin.git"
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.email", "deploy-test@example.invalid")
        self.git("config", "user.name", "Deployment Test")
        (self.project / ".gitignore").write_text(".env\n.env.*\n!.env.example\n*.pem\n*.key\n")
        (self.project / "docker-compose.yml").write_text("services: {}\n")
        for directory in ("backend", "frontend"):
            (self.project / directory).mkdir()
            (self.project / directory / ".env.example").write_text("# example\n")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.previous = self.git("rev-parse", "HEAD").strip()
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True)
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-q", "origin", "main")
        self.env_files = [self.project / name for name in (".env", "backend/.env", "frontend/.env", "backend/.env.production")]
        for path in self.env_files:
            path.write_text("SECRET=test-fixture-must-not-appear-in-output\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls.jsonl"
        self.env = dict(os.environ, EC2_PROJECT_DIR=str(self.project), DEPLOY_TEST_CALLS=str(self.calls))
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env["PATH"]
        self.tool("docker", """
import json, os, sys
args = sys.argv[1:]
with open(os.environ['DEPLOY_TEST_CALLS'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
if 'ps' in args and '-q' in args:
    if os.environ.get('DEPLOY_TEST_EXISTING_VOLUMES'):
        print('existing-' + args[-1])
elif 'inspect' in args:
    print('project_postgres_data' if args[-1] == 'existing-db' else 'project_redis_data')
elif 'config' in args and '--format' in args:
    prefix = 'other' if os.environ.get('DEPLOY_TEST_VOLUME_MISMATCH') else 'project'
    print(json.dumps({'volumes': {'postgres_data': {'name': prefix + '_postgres_data'}, 'redis_data': {'name': prefix + '_redis_data'}}}))
elif 'build' in args and os.environ.get('DEPLOY_TEST_BUILD_FAIL'):
    sys.exit(1)
""")
        self.tool("curl", "import os, sys\nsys.exit(22 if os.environ.get('DEPLOY_TEST_CURL_FAIL') else 0)\n")
        self.tool("flock", "import os, sys\nsys.exit(1 if os.environ.get('DEPLOY_TEST_LOCK_FAIL') else 0)\n")

    def tool(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.project, stderr=subprocess.PIPE, text=True)

    def target(self):
        secrets = {path: path.read_bytes() for path in self.env_files}
        (self.project / "version.txt").write_text("new tested revision\n")
        self.git("add", ".")
        self.git("commit", "-qm", "new revision")
        sha = self.git("rev-parse", "HEAD").strip()
        self.git("push", "-q", "origin", "main")
        self.git("reset", "--hard", self.previous)
        # Simulate the original untracked production files at the old revision.
        for path, contents in secrets.items():
            path.write_bytes(contents)
        return sha

    def run_deploy(self, sha):
        result = subprocess.run(["bash", str(SCRIPT), sha], env=self.env, capture_output=True, text=True)
        self.assertNotIn("test-fixture-must-not-appear-in-output", result.stdout + result.stderr)
        return result

    def docker_calls(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def test_success_preserves_secrets_and_uses_tested_revision(self):
        sha = self.target()
        originals = {path: path.read_bytes() for path in self.env_files}
        (self.project / "docker-compose.yml").write_text("local tracked edit\n")
        self.env["DEPLOY_TEST_EXISTING_VOLUMES"] = "1"
        result = self.run_deploy(sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), sha)
        for path, contents in originals.items():
            self.assertEqual(path.read_bytes(), contents)
        self.assertEqual((self.project / ".git/ec2-deploy.current").read_text().strip(), sha)
        self.assertEqual((self.project / ".git/ec2-deploy.previous").read_text().strip(), self.previous)
        calls = self.docker_calls()
        self.assertTrue(any("build" in call for call in calls))
        self.assertTrue(any("--force-recreate" in call for call in calls))
        self.assertFalse(any("down" in call or "prune" in call for call in calls))
        # Redeploying the same SHA must not discard the previous rollback target.
        self.assertEqual(self.run_deploy(sha).returncode, 0)
        self.assertEqual((self.project / ".git/ec2-deploy.previous").read_text().strip(), self.previous)

    def test_advanced_main_aborts_before_checkout(self):
        self.target()
        result = self.run_deploy(self.previous)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Main changed", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.previous)
        self.assertFalse(any("build" in call for call in self.docker_calls()))

    def test_rollback_marker_uses_last_success_after_failed_checkout(self):
        sha = self.target()
        # A failed deployment can leave HEAD ahead of the last healthy revision.
        self.git("reset", "--hard", sha)
        (self.project / ".git/ec2-deploy.current").write_text(self.previous + "\n")
        result = self.run_deploy(sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.project / ".git/ec2-deploy.previous").read_text().strip(), self.previous)

    def test_tracked_target_env_cannot_overwrite_server_secret(self):
        self.git("add", "-f", "backend/.env")
        sha = self.target()
        original = (self.project / "backend/.env").read_bytes()
        result = self.run_deploy(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected secret path is tracked", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.previous)
        self.assertEqual((self.project / "backend/.env").read_bytes(), original)

    def test_target_must_keep_ignore_rules(self):
        (self.project / ".gitignore").write_text("# ignored secrets accidentally unprotected\n")
        # Do not accidentally stage the fixture env files when making this target.
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "remove ignore rules")
        sha = self.git("rev-parse", "HEAD").strip()
        self.git("push", "-q", "origin", "main")
        self.git("reset", "--hard", self.previous)
        result = self.run_deploy(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ignore rules", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.previous)

    def test_target_file_cannot_replace_a_directory_containing_secrets(self):
        secret = self.project / "frontend/.env"
        original = secret.read_bytes()
        self.git("rm", "-r", "frontend")
        secret.unlink()
        (self.project / "frontend").rmdir()
        (self.project / "frontend").write_text("a file replacing the frontend directory\n")
        self.git("add", "frontend")
        self.git("commit", "-qm", "replace directory")
        sha = self.git("rev-parse", "HEAD").strip()
        self.git("push", "-q", "origin", "main")
        self.git("reset", "--hard", self.previous)
        secret.write_bytes(original)
        result = self.run_deploy(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("replace a secret directory", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.previous)
        self.assertEqual(secret.read_bytes(), original)

    def test_volume_rename_aborts_before_build_or_up(self):
        sha = self.target()
        self.env.update(DEPLOY_TEST_EXISTING_VOLUMES="1", DEPLOY_TEST_VOLUME_MISMATCH="1")
        result = self.run_deploy(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("persistent volume name changed", result.stderr)
        self.assertFalse(any("build" in call or "up" in call for call in self.docker_calls()))

    def test_build_failure_does_not_recreate_running_services(self):
        sha = self.target()
        self.env["DEPLOY_TEST_BUILD_FAIL"] = "1"
        result = self.run_deploy(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("up" in call for call in self.docker_calls()))
        self.assertFalse((self.project / ".git/ec2-deploy.current").exists())

    def test_health_failure_never_records_success(self):
        sha = self.target()
        self.env["DEPLOY_TEST_CURL_FAIL"] = "1"
        result = self.run_deploy(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project / ".git/ec2-deploy.current").exists())
        self.assertIn("Deployment failed", result.stderr)

    def test_server_lock_blocks_a_second_deployment(self):
        sha = self.target()
        self.env["DEPLOY_TEST_LOCK_FAIL"] = "1"
        result = self.run_deploy(sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("holds the EC2 lock", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.previous)


if __name__ == "__main__":
    unittest.main()
