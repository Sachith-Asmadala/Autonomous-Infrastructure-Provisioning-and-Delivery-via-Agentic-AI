// Exercise the actual package workflow gate against representative CI responses.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workflow = readFileSync(new URL("../../.github/workflows/packages.yml", import.meta.url), "utf8");
const script = workflow.match(/          script: \|\n([\s\S]*?)(?=\n  publish:)/)[1]
  .split("\n").map((line) => line.slice(12)).join("\n");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const requireCI = new AsyncFunction("context", "github", "core", "process", script);
const sha = "a".repeat(40);
const passing = { id: 1, head_sha: sha, head_branch: "main", event: "push",
  status: "completed", conclusion: "success" };

async function gate(runs) {
  const failures = [];
  await requireCI({ repo: { owner: "example", repo: "example" } },
    { rest: { actions: { listWorkflowRuns: async (params) => {
      assert.equal(params.workflow_id, "ci.yml");
      assert.equal(params.head_sha, sha);
      assert.equal(params.branch, "main");
      assert.equal(params.event, "push");
      return { data: { workflow_runs: runs } };
    } } } },
    { setFailed: (message) => failures.push(message), info: () => {} },
    { env: { RELEASE_SHA: sha } });
  return failures;
}

test("packages accept successful main CI for the exact release commit", async () => {
  assert.deepEqual(await gate([passing]), []);
});

for (const [name, runs] of [
  ["missing CI", []],
  ["failed CI", [{ ...passing, conclusion: "failure" }]],
  ["running CI", [{ ...passing, status: "in_progress", conclusion: null }]],
  ["different commit", [{ ...passing, head_sha: "b".repeat(40) }]],
  ["pull request CI", [{ ...passing, event: "pull_request" }]],
  ["different branch", [{ ...passing, head_branch: "develop" }]],
  ["newer failed rerun", [passing, { ...passing, id: 2, conclusion: "failure" }]],
]) {
  test(`packages refuse ${name}`, async () => {
    assert.equal((await gate(runs)).length, 1);
  });
}
