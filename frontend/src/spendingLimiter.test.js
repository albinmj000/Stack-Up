import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateSpendingLimiter,
  sumAllBankTransactions,
} from "./spendingLimiter.js";

test("spending allowance uses income, opening balance, counted expenses and savings", () => {
  const result = calculateSpendingLimiter({
    income: 64803,
    openingBalance: 7951,
    expenses: 69488,
    savingsGoal: 1131,
    periodStart: "2026-10-01",
    periodEnd: "2026-10-31",
    today: new Date(2026, 9, 14),
  });

  assert.equal(result.fundsAvailable, 72754);
  assert.equal(result.spendingLimit, 71623);
  assert.equal(result.remaining, 2135);
  assert.equal(result.usagePercent, (69488 / 71623) * 100);
  assert.equal(result.daysRemaining, 18);
  assert.equal(result.dailySafeToSpend, 118);
});

test("daily safe-to-spend is unavailable outside the statement period", () => {
  const result = calculateSpendingLimiter({
    income: 10000,
    openingBalance: 0,
    expenses: 1000,
    savingsGoal: 1000,
    periodStart: "2026-08-01",
    periodEnd: "2026-08-31",
    today: new Date(2026, 9, 14),
  });

  assert.equal(result.daysRemaining, 0);
  assert.equal(result.dailySafeToSpend, null);
});

test("over-limit expenses remain visible instead of being clamped", () => {
  const result = calculateSpendingLimiter({
    income: 10000,
    openingBalance: 0,
    expenses: 9500,
    savingsGoal: 1000,
    periodStart: "2026-10-01",
    periodEnd: "2026-10-31",
    today: new Date(2026, 9, 14),
  });

  assert.equal(result.spendingLimit, 9000);
  assert.equal(result.remaining, -500);
  assert.equal(result.usagePercent, (9500 / 9000) * 100);
  assert.equal(result.dailySafeToSpend, null);
});

test("all-transactions totals include every bank credit and debit", () => {
  const result = sumAllBankTransactions([
    { amount: 1200, type: "credit", category: "UPI Received" },
    { amount: 800, type: "debit", category: "UPI Sent" },
    { amount: 5000, type: "credit", category: "Transfer" },
    { amount: 2000, type: "debit", category: "Transfer" },
    { amount: 300, type: "debit", category: "Food" },
    { amount: 90, category: "Other" },
  ]);

  assert.deepEqual(result, { income: 6200, expenses: 3100 });
});
