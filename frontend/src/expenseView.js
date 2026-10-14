function getAmount(transaction) {
  return Math.abs(Number(
    transaction.amount ?? transaction.transaction_amount ?? 0
  )) || 0;
}

function isTransfer(transaction) {
  const transactionType = String(transaction.transaction_type ?? "").toLowerCase();
  const category = String(transaction.category ?? "").trim().toLowerCase();
  return transactionType === "transfer" ||
    ["transfer", "upi sent", "upi received"].includes(category);
}

export function summarizeExpenseView(transactions, mode) {
  const includeAllDebits = mode === "all-money-out";
  const selectedTransactions = transactions.filter((transaction) => {
    if (String(transaction.type ?? "").toLowerCase() !== "debit") {
      return false;
    }
    if (includeAllDebits) return true;

    return String(transaction.transaction_type ?? "").toLowerCase() === "expense" &&
      !isTransfer(transaction);
  });

  const total = selectedTransactions.reduce((sum, transaction) => {
    if (includeAllDebits || transaction.shared_bill_owner_share == null) {
      return sum + getAmount(transaction);
    }
    return sum + (Math.abs(Number(transaction.shared_bill_owner_share)) || 0);
  }, 0);

  return { transactions: selectedTransactions, total };
}
