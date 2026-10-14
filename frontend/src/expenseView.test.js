import assert from "node:assert/strict";
import test from "node:test";

import { summarizeExpenseView } from "./expenseView.js";

const transactions = [
  { id: 1, amount: 1200, type: "debit", transaction_type: "expense", category: "Food" },
  { id: 2, amount: 3000, type: "debit", transaction_type: "transfer", category: "Transfer" },
  { id: 3, amount: 800, type: "debit", transaction_type: "transfer", category: "UPI Sent" },
  { id: 4, amount: 900, type: "debit", transaction_type: "unknown", category: "Other" },
  { id: 5, amount: 5000, type: "credit", transaction_type: "income", category: "Salary" },
  {
    id: 6,
    amount: 4000,
    type: "debit",
    transaction_type: "expense",
    category: "Rent",
    shared_bill_owner_share: 2500,
  },
];

test("expenses-only view excludes transfers and uses shared-bill owner shares", () => {
  const result = summarizeExpenseView(transactions, "expenses-only");

  assert.deepEqual(result.transactions.map(({ id }) => id), [1, 6]);
  assert.equal(result.total, 3700);
});

test("all-money-out view includes every debit at its full bank amount", () => {
  const result = summarizeExpenseView(transactions, "all-money-out");

  assert.deepEqual(result.transactions.map(({ id }) => id), [1, 2, 3, 4, 6]);
  assert.equal(result.total, 9900);
});
