import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import worker, { handleRequest } from "../src/index.js";
import { validateReport } from "../src/schema.js";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");

function report() {
  return {
    schema_version: 1,
    skill_name: "caoyu-ai-director",
    skill_version: "1.0.0",
    event_type: "rule_violation",
    stage_code: "video_prompt",
    issue_code: "unexpected_field",
    rule_id: "R17",
    result: "fixed_locally",
    severity: "medium",
    client_version: "1.3.0",
    occurrence_count: 1,
  };
}

class MemoryD1 {
  constructor() {
    this.counts = new Map();
  }

  prepare() {
    return {
      bind: (...values) => ({
        run: async () => {
          const fingerprint = values[0];
          const count = values.at(-1);
          this.counts.set(fingerprint, (this.counts.get(fingerprint) ?? 0) + count);
          return { success: true };
        },
      }),
    };
  }
}

test("strict schema rejects private or free-text fields", () => {
  const forbidden = [
    "message",
    "prompt",
    "assistant_reply",
    "file_path",
    "url",
    "user_id",
    "device_id",
    "email",
    "password",
    "cookie",
    "ip_address",
  ];
  for (const field of forbidden) {
    assert.throws(() => validateReport({ ...report(), [field]: "private" }), /invalid_fields/);
  }
});

test("valid duplicate reports aggregate into one fingerprint", async () => {
  const db = new MemoryD1();
  const env = { DB: db };
  for (let index = 0; index < 2; index += 1) {
    const response = await handleRequest(
      new Request("https://sync.invalid/v1/reports", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(report()),
      }),
      env,
    );
    assert.equal(response.status, 202);
    assert.deepEqual(await response.json(), { accepted: true });
  }
  assert.equal(db.counts.size, 1);
  assert.equal([...db.counts.values()][0], 2);
});

test("invalid report is rejected before database access", async () => {
  const db = new MemoryD1();
  const response = await handleRequest(
    new Request("https://sync.invalid/v1/reports", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...report(), password: "not-allowed" }),
    }),
    { DB: db },
  );
  assert.equal(response.status, 400);
  assert.equal(db.counts.size, 0);
});

test("unexpected storage failure returns a generic response", async () => {
  const response = await worker.fetch(
    new Request("https://sync.invalid/v1/reports", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(report()),
    }),
    { DB: { prepare: () => { throw new Error("database details"); } } },
  );
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { accepted: false, error: "service_unavailable" });
});

test("deployment config disables observability and invocation logs", async () => {
  const config = JSON.parse(await readFile(join(root, "wrangler.jsonc"), "utf8"));
  assert.equal(config.observability.enabled, false);
  assert.equal(config.observability.logs.invocation_logs, false);
  assert.equal(config.workers_dev, true);
});

test("schema contains no raw or identity columns", async () => {
  const migration = await readFile(join(root, "migrations", "0001_init.sql"), "utf8");
  for (const forbidden of [
    "raw_payload",
    "message",
    "prompt",
    "file_path",
    "ip_address",
    "user_agent",
    "user_id",
    "device_id",
    "timestamp",
  ]) {
    assert.equal(migration.includes(forbidden), false, forbidden);
  }
});

test("worker source never reads network identity metadata", async () => {
  const source = await readFile(join(root, "src", "index.js"), "utf8");
  for (const forbidden of [
    "request.cf",
    "cf-connecting-ip",
    "user-agent",
    "cookie",
    "request.headers.entries",
  ]) {
    assert.equal(source.toLowerCase().includes(forbidden), false, forbidden);
  }
});
