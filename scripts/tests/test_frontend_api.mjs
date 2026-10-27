// Execute the actual API module to verify deployment and packaged-mode defaults.
// Run after make setup: node --test scripts/tests/test_frontend_api.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "../../frontend/node_modules/typescript/lib/typescript.js";

const source = readFileSync(new URL("../../frontend/src/services/api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
  .replace(/^import[\s\S]*?;\n/gm, "")
  .replace(/^export /gm, "")
  .replaceAll("import.meta.env", "testEnv");

function moduleContext({ desktop = false, mobile = false, env = "", saved = "" } = {}) {
  const storage = new Map(saved ? [["smart_devops_backend_url", saved]] : []);
  const context = vm.createContext({
    IS_AUTH_DISABLED: desktop, IS_DESKTOP_MODE: desktop, IS_MOBILE_MODE: mobile,
    testEnv: { VITE_API_BASE_URL: env },
    window: { location: { origin: "http://3.27.37.180" }, localStorage: {
      getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key),
    } },
    axios: { create: (config) => ({ defaults: config,
      interceptors: { request: { use: () => {} }, response: { use: () => {} } } }) },
  });
  vm.runInContext(compiled, context);
  return context;
}

test("web browser uses the deployed origin for the API", () => {
  const context = moduleContext();
  assert.equal(vm.runInContext("getApiBaseUrl()", context), "http://3.27.37.180");
  assert.equal(vm.runInContext("api.defaults.baseURL", context), "http://3.27.37.180/api/v1");
});
for (const mode of ["desktop", "mobile"]) {
  test(`${mode} keeps the local backend fallback`, () => {
    assert.equal(vm.runInContext("getApiBaseUrl()", moduleContext({ [mode]: true })), "http://127.0.0.1:8000");
  });
}
test("explicit API environment setting stays supported", () => {
  assert.equal(vm.runInContext("getApiBaseUrl()", moduleContext({ env: " https://api.example.invalid/ " })), "https://api.example.invalid");
});
test("saved backend setting takes precedence and clearing it restores same-origin", () => {
  const context = moduleContext({ env: "", saved: "https://saved.example.invalid/" });
  assert.equal(vm.runInContext("getApiBaseUrl()", context), "https://saved.example.invalid");
  vm.runInContext("clearStoredBackendUrl()", context);
  assert.equal(vm.runInContext("api.defaults.baseURL", context), "http://3.27.37.180/api/v1");
});
