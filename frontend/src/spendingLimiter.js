function wholeRupees(value) {
  const amount = Number(value);
  return Number.isFinite(amount) ? Math.round(amount) : 0;
}

export function sumAllBankTransactions(transactions) {
  return transactions.reduce((totals, transaction) => {
    const amount = Math.abs(Number(
      transaction.amount ?? transaction.transaction_amount ?? 0
    )) || 0;
    const direction = String(transaction.type ?? "").toLowerCase();
    if (direction === "credit") totals.income += amount;
    if (direction === "debit") totals.expenses += amount;
    return totals;
  }, { income: 0, expenses: 0 });
}

function dayNumber(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value ?? ""))) return null;
  const [year, month, day] = value.split("-").map(Number);
  const timestamp = Date.UTC(year, month - 1, day);
  const parsed = new Date(timestamp);
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day
  ) {
    return null;
  }
  return Math.floor(timestamp / 86_400_000);
}

function currentDayNumber(date) {
  return Math.floor(Date.UTC(
    date.getFullYear(),
    date.getMonth(),
    date.getDate()
  ) / 86_400_000);
}

export function calculateSpendingLimiter({
  income,
  openingBalance,
  expenses,
  savingsGoal,
  periodStart,
  periodEnd,
  today = new Date(),
}) {
  const incomeRupees = wholeRupees(income);
  const openingBalanceRupees = wholeRupees(openingBalance);
  const expensesRupees = wholeRupees(expenses);
  const savingsRupees = wholeRupees(savingsGoal);
  const fundsAvailable = Math.max(0, incomeRupees + openingBalanceRupees);
  const spendingLimit = Math.max(0, fundsAvailable - savingsRupees);
  const remaining = spendingLimit - expensesRupees;
  const usagePercent = spendingLimit > 0
    ? (expensesRupees / spendingLimit) * 100
    : expensesRupees > 0 ? 100 : 0;
  const startDay = dayNumber(periodStart);
  const endDay = dayNumber(periodEnd);
  const todayNumber = currentDayNumber(today);
  const daysRemaining = startDay !== null && endDay !== null &&
      todayNumber >= startDay && todayNumber <= endDay
    ? endDay - todayNumber + 1
    : 0;

  return {
    income: incomeRupees,
    openingBalance: openingBalanceRupees,
    fundsAvailable,
    expenses: expensesRupees,
    savingsGoal: savingsRupees,
    spendingLimit,
    remaining,
    usagePercent,
    daysRemaining,
    dailySafeToSpend: daysRemaining > 0 && remaining >= 0
      ? Math.floor(remaining / daysRemaining)
      : null,
  };
}
