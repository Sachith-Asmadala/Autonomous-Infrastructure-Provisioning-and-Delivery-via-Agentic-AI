// Execute the actual GitHub Actions CI gate with mocked GitHub API responses.
// Run: node --test scripts/tests/test_deployment_workflow.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workflow = readFileSync(new URL("../../.github/workflows/deploy.yml", import.meta.url), "utf8");
const script = workflow.match(/          script: \|\n([\s\S]*?)(?=\n      - name:)/)[1]
  .split("\n").map((line) => line.slice(12)).join("\n");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const selectRevision = new AsyncFunction("context", "github", "core", script);
const sha = "a".repeat(40);

async function gate({ event = "workflow_dispatch", head = sha, run } = {}) {
  const outputs = {};
  const failures = [];
  const github = { rest: {
    repos: { getBranch: async () => ({ data: { commit: { sha } } }) },
    actions: { listWorkflowRuns: async (params) => {
      assert.equal(params.workflow_id, "ci.yml");
      assert.equal(params.head_sha, sha);
      assert.equal(params.event, "push");
      assert.equal(params.branch, "main");
      return { data: { workflow_runs: run ? [run] : [] } };
    } },
  } };
  await selectRevision(
    { repo: { owner: "example", repo: "example" }, eventName: event,
      payload: { workflow_run: { head_sha: head } } },
    github,
    { notice: () => {}, setFailed: (message) => failures.push(message),
      setOutput: (key, value) => { outputs[key] = value; } },
  );
  return { outputs, failures };
}

test("manual deployment refuses a revision without CI", async () => {
  const result = await gate();
  assert.equal(result.failures.length, 1);
  assert.notEqual(result.outputs.ready, "true");
});
for (const [status, conclusion] of [["completed", "failure"], ["completed", "cancelled"], ["in_progress", null]]) {
  test(`manual deployment refuses CI ${status}/${conclusion}`, async () => {
    const result = await gate({ run: { status, conclusion } });
    assert.equal(result.failures.length, 1);
    assert.notEqual(result.outputs.ready, "true");
  });
}
test("stale automatic CI result cannot deploy newer untested main", async () => {
  const result = await gate({ event: "workflow_run", head: "b".repeat(40) });
  assert.equal(result.outputs.ready, "false");
  assert.equal(result.failures.length, 0);
});
for (const event of ["workflow_run", "workflow_dispatch"]) {
  test(`${event} selects only the latest passing revision`, async () => {
    const result = await gate({ event, run: { status: "completed", conclusion: "success" } });
    assert.deepEqual(result.outputs, { sha, ready: "true" });
    assert.equal(result.failures.length, 0);
  });
}
