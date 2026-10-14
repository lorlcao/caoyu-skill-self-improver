export const SCHEMA_VERSION = 1;
export const MAX_BODY_BYTES = 4096;

export const EVENT_TYPES = Object.freeze([
  "rule_violation",
  "tool_failure",
  "workflow_break",
  "regression",
  "fix_verified",
]);

export const STAGE_CODES = Object.freeze([
  "routing",
  "input_validation",
  "asset_generation",
  "script_generation",
  "storyboard",
  "image_generation",
  "video_prompt",
  "spreadsheet",
  "tool_execution",
  "packaging",
  "other",
]);

export const ISSUE_CODES = Object.freeze([
  "rule_not_followed",
  "missing_required_output",
  "unexpected_field",
  "wrong_stage_order",
  "tool_error",
  "format_error",
  "continuity_error",
  "permission_blocked",
  "regression",
  "other_categorized",
]);

export const RESULTS = Object.freeze([
  "observed",
  "fixed_locally",
  "verified_pass",
  "unresolved",
]);

export const SEVERITIES = Object.freeze(["low", "medium", "high"]);

export const REPORT_KEYS = Object.freeze([
  "schema_version",
  "skill_name",
  "skill_version",
  "event_type",
  "stage_code",
  "issue_code",
  "rule_id",
  "result",
  "severity",
  "client_version",
  "occurrence_count",
]);

const SEMVER = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/;
const SKILL_NAME = /^[a-z0-9][a-z0-9-]{0,63}$/;
const RULE_ID = /^[A-Z0-9][A-Z0-9_-]{0,23}$/;

function exactKeys(value) {
  const actual = Object.keys(value).sort();
  const expected = [...REPORT_KEYS].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

export function validateReport(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value) || !exactKeys(value)) {
    throw new Error("invalid_fields");
  }
  if (value.schema_version !== SCHEMA_VERSION) throw new Error("invalid_schema_version");
  if (typeof value.skill_name !== "string" || !SKILL_NAME.test(value.skill_name)) {
    throw new Error("invalid_skill_name");
  }
  if (typeof value.skill_version !== "string" || !SEMVER.test(value.skill_version)) {
    throw new Error("invalid_skill_version");
  }
  if (typeof value.client_version !== "string" || !SEMVER.test(value.client_version)) {
    throw new Error("invalid_client_version");
  }
  if (!EVENT_TYPES.includes(value.event_type)) throw new Error("invalid_event_type");
  if (!STAGE_CODES.includes(value.stage_code)) throw new Error("invalid_stage_code");
  if (!ISSUE_CODES.includes(value.issue_code)) throw new Error("invalid_issue_code");
  if (!RESULTS.includes(value.result)) throw new Error("invalid_result");
  if (!SEVERITIES.includes(value.severity)) throw new Error("invalid_severity");
  if (typeof value.rule_id !== "string" || !RULE_ID.test(value.rule_id)) {
    throw new Error("invalid_rule_id");
  }
  if (
    !Number.isInteger(value.occurrence_count) ||
    value.occurrence_count < 1 ||
    value.occurrence_count > 100
  ) {
    throw new Error("invalid_occurrence_count");
  }
  return value;
}

export async function fingerprintReport(report) {
  const normalized = { ...validateReport(report), occurrence_count: 0 };
  const canonical = JSON.stringify(
    Object.fromEntries(REPORT_KEYS.map((key) => [key, normalized[key]])),
  );
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
