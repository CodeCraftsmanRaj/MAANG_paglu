/**
 * Unit Test Suite for formatProvenance (6 Canonical Test Cases)
 */
import assert from "node:assert";
import { formatProvenance, extractDomain, formatKindLabel } from "./provenance.js";

console.log("Running formatProvenance unit tests...\n");

// Fixed deterministic anchor time: Sep 20, 2026, 3:50 AM UTC
const fixedNow = new Date("2026-09-20T03:50:00Z").getTime();
// 1 day prior: Sep 19, 2026, 3:50 AM UTC
const fixedRecordedAt = "2026-09-19T03:50:00Z";

// Case 1: Pasted note with generic title
const case1 = formatProvenance(
  {
    kind: "text",
    source_kind_label: "a pasted note",
    source_label: 'starting "Deploy checklist for database..."',
    project_id: "proj_default",
    project_name: "Default Workspace",
    recorded_at: fixedRecordedAt,
  },
  { id: "proj_default", name: "Default Workspace" },
  "en-US",
  fixedNow
);
console.log("Case 1 (Pasted note with generic title):", case1);
assert.match(case1, /^From a pasted note starting "Deploy checklist for database...", .* \(yesterday\)\.$/);

// Case 2: URL source
const case2 = formatProvenance(
  {
    kind: "url",
    source_kind_label: "a web page",
    source_label: '"Engineering Runbook"',
    source_domain: "notion.so",
    uri: "https://notion.so/engineering/runbook",
    project_id: "proj_default",
    project_name: "Default Workspace",
    recorded_at: fixedRecordedAt,
  },
  { id: "proj_default", name: "Default Workspace" },
  "en-US",
  fixedNow
);
console.log("Case 2 (URL source with domain):", case2);
assert.match(case2, /^From a web page on notion\.so \("Engineering Runbook"\), .* \(yesterday\)\.$/);

// Case 3: Screenshot (OCR)
const case3 = formatProvenance(
  {
    kind: "screenshot",
    source_kind_label: "a screenshot (OCR)",
    source_label: 'starting "AWS Billing Console dashboard..."',
    project_id: "proj_default",
    project_name: "Default Workspace",
    recorded_at: fixedRecordedAt,
  },
  { id: "proj_default", name: "Default Workspace" },
  "en-US",
  fixedNow
);
console.log("Case 3 (Screenshot OCR):", case3);
assert.match(case3, /^From a screenshot \(OCR\) starting "AWS Billing Console dashboard\.\.\.", .* \(yesterday\)\.$/);

// Case 4: Live source
const case4 = formatProvenance(
  {
    kind: "session",
    source_kind_label: "a live session",
    source_label: '"Incident Bridge #402"',
    source_mode: "live",
    project_id: "proj_default",
    project_name: "Default Workspace",
    recorded_at: fixedRecordedAt,
  },
  { id: "proj_default", name: "Default Workspace" },
  "en-US",
  fixedNow
);
console.log("Case 4 (Live source):", case4);
assert.match(case4, /^From a live session "Incident Bridge #402" \(synced live\), .* \(yesterday\)\.$/);

// Case 5: Restricted source
const case5 = formatProvenance(
  {
    is_restricted: true,
    kind: "restricted",
    source_label: "a restricted source",
  },
  { id: "proj_default", name: "Default Workspace" },
  "en-US",
  fixedNow
);
console.log("Case 5 (Restricted source):", case5);
assert.strictEqual(case5, "From a restricted source.");

// Case 6: Source in a different project
const case6 = formatProvenance(
  {
    kind: "file",
    source_kind_label: "a file",
    source_label: '"config.yaml"',
    project_id: "proj_core",
    project_name: "Core Platform",
    recorded_at: fixedRecordedAt,
  },
  { id: "proj_frontend", name: "Frontend Portal" },
  "en-US",
  fixedNow
);
console.log("Case 6 (Source in different project):", case6);
assert.match(case6, /^From a file "config\.yaml", in Core Platform, .* \(yesterday\)\.$/);

console.log("\nALL 6 PROVENANCE FORMATTER UNIT TESTS PASSED!");
