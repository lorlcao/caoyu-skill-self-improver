import { MAX_BODY_BYTES, REPORT_KEYS, fingerprintReport, validateReport } from "./schema.js";

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

async function storeAggregate(db, report) {
  const fingerprint = await fingerprintReport(report);
  const columns = REPORT_KEYS.filter((key) => key !== "occurrence_count").sort();
  const placeholders = columns.map(() => "?").join(", ");
  const sql = `
    INSERT INTO aggregates (fingerprint, ${columns.join(", ")}, occurrence_count)
    VALUES (?, ${placeholders}, ?)
    ON CONFLICT(fingerprint) DO UPDATE SET
      occurrence_count = occurrence_count + excluded.occurrence_count
  `;
  const values = columns.map((column) => report[column]);
  await db.prepare(sql).bind(fingerprint, ...values, report.occurrence_count).run();
}

async function receiveReport(request, env) {
  if (request.headers.get("content-type")?.split(";", 1)[0].trim() !== "application/json") {
    return json({ accepted: false, error: "invalid_content_type" }, 415);
  }
  const body = await request.text();
  if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES) {
    return json({ accepted: false, error: "body_too_large" }, 413);
  }
  let report;
  try {
    report = validateReport(JSON.parse(body));
  } catch {
    return json({ accepted: false, error: "invalid_report" }, 400);
  }
  await storeAggregate(env.DB, report);
  return json({ accepted: true }, 202);
}

export async function handleRequest(request, env) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/health") {
    return json({ ok: true, schema_version: 1 });
  }
  if (request.method === "GET" && url.pathname === "/v1/releases/latest") {
    return json({ skill_name: url.searchParams.get("skill_name") ?? "", release: null });
  }
  if (request.method === "POST" && url.pathname === "/v1/reports") {
    return receiveReport(request, env);
  }
  return json({ error: "not_found" }, 404);
}

export default {
  async fetch(request, env) {
    try {
      return await handleRequest(request, env);
    } catch {
      return json({ accepted: false, error: "service_unavailable" }, 503);
    }
  },
};
