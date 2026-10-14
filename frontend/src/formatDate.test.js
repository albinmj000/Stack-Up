import assert from "node:assert/strict";
import test from "node:test";

import { formatDate } from "./formatDate.js";

const options = { day: "2-digit", month: "short", year: "numeric" };

test("formats bank dates as day-month-year instead of browser-dependent dates", () => {
  assert.equal(
    formatDate("12-09-2026"),
    new Date(2026, 8, 12).toLocaleDateString("en-IN", options),
  );
  assert.equal(
    formatDate("11-10-2026"),
    new Date(2026, 9, 11).toLocaleDateString("en-IN", options),
  );
});

test("formats ISO date-only values without timezone shifts", () => {
  assert.equal(
    formatDate("2026-09-12"),
    new Date(2026, 8, 12).toLocaleDateString("en-IN", options),
  );
});

test("preserves timestamps and invalid date labels", () => {
  assert.equal(
    formatDate("not a date"),
    "not a date",
  );
  assert.notEqual(
    formatDate("2026-09-12T00:00:00Z"),
    "not a date",
  );
});
