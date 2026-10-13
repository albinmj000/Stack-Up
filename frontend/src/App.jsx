import { useEffect, useRef, useState } from "react";
import {
  LayoutDashboard,
  ArrowLeftRight,
  ChartNoAxesCombined,
  X,
  Activity,
  MessageCircle,
  Upload,
  Search,
  ArrowUpRight,
  ArrowDownRight,
  Wallet,
  PiggyBank,
  Menu,
  Sparkles,
  CircleHelp,
  History,
  Download,
  Trash2,
  Users,
  Plus,
  LogOut,
  Settings,
} from "lucide-react";
import stackUpLogo from "./assets/stackup-logo.svg";
import stackUpLightLogo from "./assets/stackup-logo-light.svg";
import { API, readApiResponse } from "./api";
import AccountSettings from "./AccountSettings";
import "./App.css";

const CATEGORY_OPTIONS = [
  "Food", "Transport", "Shopping", "Bills & Utilities",
  "Entertainment", "Healthcare", "Loan / Credit", "Bank Charges",
  "Cash Withdrawal", "Investment", "Income", "Interest Income", "Refund",
  "Transfer", "UPI Sent", "UPI Received", "Other",
];

const navigation = [
  { label: "Dashboard", icon: LayoutDashboard },
  { label: "Transactions", icon: ArrowLeftRight },
  { label: "Transaction Trends", icon: Activity },
  { label: "Analytics", icon: ChartNoAxesCombined },
  { label: "AI Assistant", icon: MessageCircle },
  { label: "Statement History", icon: History },
];

const money = (value) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(Number(value) || 0);

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      });
}

function getTransactionDateKey(value) {
  const text = String(value ?? "").trim();
  if (!text) return "Unknown date";

  const yearFirst = text.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})/);
  if (yearFirst) {
    return `${yearFirst[1]}-${yearFirst[2].padStart(2, "0")}-${yearFirst[3].padStart(2, "0")}`;
  }

  const dayFirst = text.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})/);
  if (dayFirst) {
    const year = dayFirst[3].length === 2 ? `20${dayFirst[3]}` : dayFirst[3];
    return `${year}-${dayFirst[2].padStart(2, "0")}-${dayFirst[1].padStart(2, "0")}`;
  }

  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text;
  return [
    parsed.getFullYear(),
    String(parsed.getMonth() + 1).padStart(2, "0"),
    String(parsed.getDate()).padStart(2, "0"),
  ].join("-");
}

function getAmount(transaction) {
  const value = transaction.amount ?? transaction.transaction_amount ?? 0;
  return Math.abs(Number(value) || 0);
}

function getCountedExpenseAmount(transaction) {
  return transaction.shared_bill_owner_share == null
    ? getAmount(transaction)
    : Math.abs(Number(transaction.shared_bill_owner_share) || 0);
}

function getTransactionType(transaction) {
  const text = `${transaction.type ?? ""} ${transaction.transaction_type ?? ""} ${transaction.category ?? ""}`.toLowerCase();
  if (text.includes("income") || text.includes("credit") || text.includes("deposit")) {
    return "income";
  }
  return "expense";
}

function getTransactionFilterType(transaction) {
  if (transaction.income_included) return "income";
  if (getAnalyticsCategory(transaction) === "UPI Received") {
    return "income";
  }
  const transactionType = String(transaction.transaction_type ?? "").toLowerCase();
  if (["income", "expense", "transfer", "unknown"].includes(transactionType)) {
    return transactionType;
  }
  const direction = String(transaction.type ?? "").toLowerCase();
  if (direction === "credit") return "income";
  if (direction === "debit") return "expense";
  return "unknown";
}

function getAmountDirection(transaction) {
  const direction = String(transaction.type ?? "").toLowerCase();
  if (direction === "credit") return "income";
  if (direction === "debit") return "expense";
  return getTransactionType(transaction);
}

function getTransactionName(transaction) {
  return (
    transaction.description ??
    transaction.merchant ??
    transaction.name ??
    transaction.narration ??
    "Transaction"
  );
}

function getTransactionCategory(transaction) {
  return transaction.category ?? transaction.type ?? "Other";
}

function getAnalyticsCategory(transaction) {
  const category = getTransactionCategory(transaction);
  if (String(category).trim().toLowerCase() === "transfer" && /\bupi\b/i.test(transaction.description ?? "")) {
    return String(transaction.type ?? "").toLowerCase() === "credit"
      ? "UPI Received"
      : "UPI Sent";
  }
  return category;
}

function isUpiActivity(transaction, activity) {
  return String(getAnalyticsCategory(transaction)).trim().toLowerCase() === `upi ${activity}`;
}

function getFollowUpQuestions(result, askedQuestion = "") {
  if (Array.isArray(result.follow_up_questions) && result.follow_up_questions.length) {
    return result.follow_up_questions;
  }

  const category = result.category ?? result.data?.category;
  if (category) {
    return [
      `Show all ${category} transactions`,
      `What is my total for ${category}?`,
      "Where did I spend the most?",
    ];
  }

  if (result.data?.highest_spending_category) {
    return [
      `Show all ${result.data.highest_spending_category} transactions`,
      "How can I save more?",
      "Summarize my statement",
    ];
  }

  if (result.data?.category_totals) {
    return [
      "Where did I spend the most?",
      "Show all Other transactions",
      "How can I save more?",
    ];
  }

  if (result.data?.total_income !== undefined) {
    return [
      "Show all Income transactions",
      "What is my net cash flow?",
      "What is my savings rate?",
    ];
  }

  if (result.data?.total_expenses !== undefined) {
    return [
      "Where did I spend the most?",
      "How can I save more?",
      "Show all Other transactions",
    ];
  }

  const question = askedQuestion.toLowerCase();
  if (question.includes("balance")) {
    return [
      "What is my net cash flow?",
      "Show all Income transactions",
      "Show all Other transactions",
    ];
  }

  return [
    "Where did I spend the most?",
    "How can I save more?",
    "Summarize my statement",
  ];
}

function AuthScreen({ onAuthenticated, initialNotice = "" }) {
  const [mode, setMode] = useState("login");
  const [stage, setStage] = useState("form");
  const [useOtpLogin, setUseOtpLogin] = useState(false);
  const [username, setUsername] = useState("");
  const [contact, setContact] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(initialNotice);

  async function submitPasswordLogin(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password }),
      });
      const result = await readApiResponse(response);
      if (!response.ok) throw new Error(result.detail || "Could not sign in.");
      onAuthenticated(result.account);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function sendCode(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/auth/request-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contact,
          create_account: mode === "create",
          username: mode === "create" ? username : undefined,
          password: mode === "create" ? password : undefined,
        }),
      });
      const result = await readApiResponse(response);
      if (!response.ok) throw new Error(result.detail || "Could not send a code.");
      setStage("verify");
      setNotice(result.message || "Enter the verification code we sent you.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function verifyCode(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/auth/verify-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ contact, code }),
      });
      const result = await readApiResponse(response);
      if (!response.ok) throw new Error(result.detail || "Could not verify that code.");
      onAuthenticated(result.account);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-screen">
      <section className="auth-card">
        <a className="brand auth-brand" href="#" onClick={(event) => event.preventDefault()}>
          <img className="brand-image" src={stackUpLogo} alt="Stack Up Personal Finance" />
        </a>
        <h1>{mode === "login" ? "Welcome back." : "Create your account."}</h1>
        <p className="auth-subtitle">{mode === "login" ? "Sign in with your username and password." : "Create login credentials and verify your email or phone."}</p>
        {stage === "form" && notice && <p className="auth-notice" role="status">{notice}</p>}

        {stage === "form" ? (
          <>
            <div className="auth-mode-switch">
              <button type="button" className={mode === "login" ? "active" : ""} onClick={() => { setMode("login"); setUseOtpLogin(false); setError(""); }}>Sign in</button>
              <button type="button" className={mode === "create" ? "active" : ""} onClick={() => { setMode("create"); setUseOtpLogin(false); setError(""); }}>Create account</button>
            </div>
            {mode === "login" && !useOtpLogin ? (
              <form className="auth-form" onSubmit={submitPasswordLogin}>
                <label htmlFor="auth-username">Username</label>
                <input id="auth-username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="Your username" required />
                <label htmlFor="auth-password">Password</label>
                <input id="auth-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Your password" required />
                <button className="primary-button auth-submit" type="submit" disabled={busy}>
                  {busy ? "Signing in..." : "Sign in"}
                </button>
                <button className="auth-back-button" type="button" onClick={() => setUseOtpLogin(true)}>Sign in with an email or phone code</button>
              </form>
            ) : (
              <form className="auth-form" onSubmit={sendCode}>
                {mode === "create" && <>
                  <label htmlFor="auth-username">Username</label>
                  <input id="auth-username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="3–24 letters, numbers, . _ or -" minLength={3} maxLength={24} required />
                  <label htmlFor="auth-password">Create password</label>
                  <input id="auth-password" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 8 characters" minLength={8} maxLength={128} required />
                </>}
                <label htmlFor="auth-contact">{mode === "create" ? "Email or phone for verification" : "Email or phone number"}</label>
                <input id="auth-contact" autoComplete="email" value={contact} onChange={(event) => setContact(event.target.value)} placeholder="you@example.com or +91 98765 43210" required />
                <button className="primary-button auth-submit" type="submit" disabled={busy}>
                  {busy ? "Sending code..." : mode === "create" ? "Verify email or phone" : "Send sign-in code"}
                </button>
                {mode === "login" && <button className="auth-back-button" type="button" onClick={() => setUseOtpLogin(false)}>Back to username and password</button>}
              </form>
            )}
          </>
        ) : (
          <form className="auth-form" onSubmit={verifyCode}>
            <p className="auth-notice">{notice}</p>
            <label htmlFor="auth-code">6-digit verification code</label>
            <input
              id="auth-code"
              autoComplete="one-time-code"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
              placeholder="123456"
              required
            />
            <button className="primary-button auth-submit" type="submit" disabled={busy || code.length !== 6}>
              {busy ? "Verifying..." : "Verify and continue"}
            </button>
            <button className="auth-back-button" type="button" onClick={() => { setStage("form"); setNotice(""); setCode(""); }}>
              Back to account details
            </button>
          </form>
        )}
        {error && <p className="auth-error" role="alert">{error}</p>}
        <p className="auth-privacy">Usernames and verified email addresses or phone numbers must be unique. Passwords are stored securely.</p>
      </section>
    </main>
  );
}

function App() {
  const [activePage, setActivePage] = useState("Dashboard");
  const [theme, setTheme] = useState("dark");
  const [account, setAccount] = useState(null);
  const [rememberedAccounts, setRememberedAccounts] = useState([]);
  const [authLoading, setAuthLoading] = useState(true);
  const [accountSwitching, setAccountSwitching] = useState(false);
  const [authNotice, setAuthNotice] = useState("");
  const [mobileMenu, setMobileMenu] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [combinedData, setCombinedData] = useState(null);
  const [combinedLoading, setCombinedLoading] = useState(false);
  const [combinedError, setCombinedError] = useState("");
  const [combinedRefreshKey, setCombinedRefreshKey] = useState(0);
  const [sharedBillRefreshKey, setSharedBillRefreshKey] = useState(0);
  const [sharedBills, setSharedBills] = useState([]);
  const [sharedBillFormOpen, setSharedBillFormOpen] = useState(false);
  const [sharedBillTransactionId, setSharedBillTransactionId] = useState("");
  const [sharedBillTitle, setSharedBillTitle] = useState("");
  const [sharedBillOwnerShare, setSharedBillOwnerShare] = useState("");
  const [sharedBillParticipants, setSharedBillParticipants] = useState([
    { name: "", share_amount: "" },
  ]);
  const [sharedBillBusy, setSharedBillBusy] = useState(false);
  const [selectedDashboardStatementIds, setSelectedDashboardStatementIds] = useState(null);
  const [dashboardSelectionData, setDashboardSelectionData] = useState(null);
  const [dashboardSelectionLoading, setDashboardSelectionLoading] = useState(false);
  const [statements, setStatements] = useState([]);
  const [bankAccounts, setBankAccounts] = useState([]);
  const [bankAccountDraft, setBankAccountDraft] = useState("");
  const [uploadBankAccountId, setUploadBankAccountId] = useState("");
  const [activeStatementId, setActiveStatementId] = useState(null);
  const [aiStatementIds, setAiStatementIds] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [selectedMetric, setSelectedMetric] = useState(null);
  const [incomeInclusionBusyId, setIncomeInclusionBusyId] = useState(null);
  const [metricFilters, setMetricFilters] = useState({
    category: "all",
    type: "all",
    fromDate: "",
    toDate: "",
    minAmount: "",
    maxAmount: "",
  });
  const [transactionFilters, setTransactionFilters] = useState({
    category: "all",
    type: "all",
    fromDate: "",
    toDate: "",
    minAmount: "",
    maxAmount: "",
  });
  const [savingsGoals, setSavingsGoals] = useState(() => {
    try {
      return JSON.parse(window.localStorage.getItem("stackup:savings-goals") || "{}");
    } catch {
      return {};
    }
  });
  const [savingsGoalDraft, setSavingsGoalDraft] = useState("");
  const [savingsGoalError, setSavingsGoalError] = useState("");
  const [selectedTimelineDate, setSelectedTimelineDate] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const chatInputRef = useRef(null);
  const savingsAccountKey = String(
    account?.user_id ?? account?.id ?? account?.username ?? account?.email ?? account?.phone ?? ""
  );
  const statementIdsKey = statements
    .map((statement) => statement.statement_id)
    .join(",");

  useEffect(() => {
    if (!account || !statements.length) {
      setCombinedData(null);
      setCombinedError("");
      setCombinedLoading(false);
      return undefined;
    }

    let cancelled = false;
    async function loadCombinedStatements() {
      setCombinedLoading(true);
      setCombinedError("");
      setCombinedData(null);
      try {
        const response = await fetch(`${API}/statements/combined`, {
          credentials: "include",
        });
        const result = await readApiResponse(response);
        if (!response.ok) {
          throw new Error(result.detail || "Could not load combined statements.");
        }
        if (!cancelled) {
          setCombinedData({
            transactions: Array.isArray(result.transactions) ? result.transactions : [],
            analysis: result.analysis ?? null,
            statementCount: Number(result.statement_count) || 0,
          });
        }
      } catch (loadError) {
        if (!cancelled) {
          setCombinedError(loadError.message);
          setCombinedData(null);
        }
      } finally {
        if (!cancelled) setCombinedLoading(false);
      }
    }

    loadCombinedStatements();
    return () => {
      cancelled = true;
    };
  }, [account, statementIdsKey, statements.length, combinedRefreshKey]);

  useEffect(() => {
    setSharedBills([]);
    setSharedBillFormOpen(false);
    setSharedBillTransactionId("");
    setSharedBillTitle("");
    setSharedBillOwnerShare("");
    setSharedBillParticipants([{ name: "", share_amount: "" }]);
  }, [savingsAccountKey]);

  useEffect(() => {
    if (!account) {
      setSharedBills([]);
      return undefined;
    }

    let cancelled = false;
    async function loadSharedBills() {
      try {
        const response = await fetch(`${API}/shared-bills`, {
          credentials: "include",
        });
        const result = await readApiResponse(response);
        if (!response.ok) {
          throw new Error(result.detail || "Could not load shared bills.");
        }
        if (!cancelled) {
          setSharedBills(Array.isArray(result.shared_bills) ? result.shared_bills : []);
        }
      } catch (loadError) {
        if (!cancelled) setError(loadError.message);
      }
    }
    loadSharedBills();
    return () => {
      cancelled = true;
    };
  }, [account, sharedBillRefreshKey]);

  useEffect(() => {
    if (selectedDashboardStatementIds === null) {
      setDashboardSelectionData(null);
      setDashboardSelectionLoading(false);
      return undefined;
    }
    let cancelled = false;
    async function loadDashboardSelection() {
      if (selectedDashboardStatementIds.length === 0) {
        setDashboardSelectionData({ transactions: [], analysis: null });
        return;
      }
      setDashboardSelectionData(null);
      setDashboardSelectionLoading(true);
      setError("");
      try {
        const params = new URLSearchParams();
        selectedDashboardStatementIds.forEach((statementId) => {
          params.append("statement_ids", String(statementId));
        });
        const response = await fetch(`${API}/statements/selection?${params}`, {
          credentials: "include",
        });
        const result = await readApiResponse(response);
        if (!response.ok) throw new Error(result.detail || "Could not calculate the selected statements.");
        if (!cancelled) {
          setDashboardSelectionData({
            transactions: Array.isArray(result.transactions) ? result.transactions : [],
            analysis: result.analysis ?? null,
          });
        }
      } catch (selectionError) {
        if (!cancelled) {
          setDashboardSelectionData(null);
          setError(selectionError.message);
        }
      } finally {
        if (!cancelled) setDashboardSelectionLoading(false);
      }
    }
    loadDashboardSelection();
    return () => {
      cancelled = true;
    };
  }, [selectedDashboardStatementIds, statementIdsKey, combinedRefreshKey]);

  useEffect(() => {
    if (savingsAccountKey) {
      setSavingsGoalDraft(String(savingsGoals[savingsAccountKey] ?? ""));
    } else {
      setSavingsGoalDraft("");
    }
    setSavingsGoalError("");
  }, [savingsAccountKey]);

  useEffect(() => {
    if (!savingsAccountKey) {
      setTheme("dark");
      return;
    }
    try {
      const savedTheme = window.localStorage.getItem(`stackup:theme:${savingsAccountKey}`);
      setTheme(savedTheme === "light" ? "light" : "dark");
    } catch {
      setTheme("dark");
    }
  }, [savingsAccountKey]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    try {
      window.localStorage.setItem("stackup:savings-goals", JSON.stringify(savingsGoals));
    } catch {
      // The limit remains usable for this session when browser storage is unavailable.
    }
  }, [savingsGoals]);

  useEffect(() => {
    setMetricFilters({
      category: "all",
      type: "all",
      fromDate: "",
      toDate: "",
      minAmount: "",
      maxAmount: "",
    });
  }, [selectedMetric]);

  useEffect(() => {
    if (!selectedCategory) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setSelectedCategory(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [selectedCategory]);

  async function refreshStatementHistory() {
    const response = await fetch(`${API}/statements`, { credentials: "include" });
    if (!response.ok) throw new Error("Could not load statement history.");
    const result = await readApiResponse(response);
    const nextStatements = Array.isArray(result.statements) ? result.statements : [];
    setStatements(nextStatements);
    const accountsResponse = await fetch(`${API}/bank-accounts`, { credentials: "include" });
    const accountsResult = await readApiResponse(accountsResponse);
    if (!accountsResponse.ok) {
      throw new Error(accountsResult.detail || "Could not load your bank accounts.");
    }
    setBankAccounts(Array.isArray(accountsResult.bank_accounts) ? accountsResult.bank_accounts : []);
    setUploadBankAccountId((current) => (
      accountsResult.bank_accounts?.some((item) => String(item.id) === current) ? current : ""
    ));
    setSelectedDashboardStatementIds((current) => current === null
      ? null
      : current.filter((id) => nextStatements.some((statement) => statement.statement_id === id)));
    setAiStatementIds((current) => {
      const available = new Set(nextStatements.map((statement) => statement.statement_id));
      const stillAvailable = current.filter((id) => available.has(id));
      return stillAvailable.length ? stillAvailable : nextStatements[0] ? [nextStatements[0].statement_id] : [];
    });
    return nextStatements;
  }

  async function loadSavedStatement(statementId) {
    const response = await fetch(`${API}/statements/${statementId}`, { credentials: "include" });
    const result = await readApiResponse(response);
    if (!response.ok) throw new Error(result.detail || "Could not load this statement.");
    setActiveStatementId(result.statement_id ?? statementId);
    setAiStatementIds([result.statement_id ?? statementId]);
    setMessages([]);
    setActivePage("Dashboard");
    setNotice(`${result.filename || "Statement"} loaded from history.`);
    setError("");
  }

  async function selectDashboardStatement(value) {
    if (value === "all") {
      setSelectedDashboardStatementIds(null);
      setError("");
      return;
    }

    const statementId = Number(value);
    if (!Number.isInteger(statementId)) {
      setError("Choose a valid statement.");
      return;
    }

    const target = statements.find((statement) => statement.statement_id === statementId);
    if (!target) {
      setError("Choose a valid statement.");
      return;
    }
    const current = selectedDashboardStatementIds
      ?? statements.map((statement) => statement.statement_id);
    setSelectedDashboardStatementIds(current.includes(statementId)
      ? current.filter((id) => id !== statementId)
      : [...current, statementId]);
    setError("");
  }

  function toggleDashboardStatementGroup(groupStatements, checked) {
    const current = selectedDashboardStatementIds
      ?? statements.map((statement) => statement.statement_id);
    const groupIds = groupStatements.map((statement) => statement.statement_id);
    const nextIds = checked
      ? [...new Set([...current, ...groupIds])]
      : current.filter((id) => !groupIds.includes(id));
    setSelectedDashboardStatementIds(nextIds.length === statements.length ? null : nextIds);
  }

  async function createBankAccount(event) {
    event.preventDefault();
    const name = bankAccountDraft.trim();
    if (!name) return;
    try {
      const response = await fetch(`${API}/bank-accounts`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const result = await readApiResponse(response);
      if (!response.ok) throw new Error(result.detail || "Could not add the bank account.");
      const created = result.bank_account;
      setBankAccounts((current) => [...current, created].sort((a, b) => a.name.localeCompare(b.name)));
      setUploadBankAccountId(String(created.id));
      setBankAccountDraft("");
      setNotice(`${created.name} added. Assign statements to it from the selector or statement history.`);
      setError("");
    } catch (createError) {
      setError(createError.message);
    }
  }

  async function assignStatementToBankAccount(statementId, value) {
    const bankAccountId = value ? Number(value) : null;
    try {
      const response = await fetch(`${API}/statements/${statementId}/bank-account`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bank_account_id: bankAccountId }),
      });
      const result = await readApiResponse(response);
      if (!response.ok) throw new Error(result.detail || "Could not assign this statement.");
      const bankAccount = bankAccounts.find((item) => item.id === bankAccountId);
      setStatements((current) => current.map((statement) => statement.statement_id === statementId
        ? { ...statement, bank_account_id: bankAccountId, bank_account_name: bankAccount?.name ?? null }
        : statement));
      setNotice(bankAccount
        ? `Statement linked to ${bankAccount.name}.`
        : "Statement moved to Unassigned.");
      setError("");
    } catch (assignError) {
      setError(assignError.message);
    }
  }

  async function finishSignIn(nextAccount) {
    setAccount(nextAccount);
    setSelectedDashboardStatementIds(null);
    setUploadBankAccountId("");
    setDashboardSelectionData(null);
    setCombinedData(null);
    setStatements([]);
    setBankAccounts([]);
    setAiStatementIds([]);
    setActiveStatementId(null);
    setAuthNotice("");
    setAuthLoading(true);
    try {
      const accountsResponse = await fetch(`${API}/auth/accounts`, { credentials: "include" });
      if (accountsResponse.ok) {
        const accountsResult = await readApiResponse(accountsResponse);
        setRememberedAccounts(Array.isArray(accountsResult.accounts) ? accountsResult.accounts : []);
      }
      const history = await refreshStatementHistory();
      if (history.length > 0) await loadSavedStatement(history[0].statement_id);
      else {
        setActiveStatementId(null);
        setActivePage("Dashboard");
      }
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function signOut() {
    try {
      await fetch(`${API}/auth/logout`, { method: "POST", credentials: "include" });
    } finally {
      setAccount(null);
      setRememberedAccounts([]);
      setStatements([]);
      setBankAccounts([]);
      setDashboardSelectionData(null);
      setCombinedData(null);
      setActiveStatementId(null);
      setMessages([]);
      setQuestion("");
      setSelectedCategory(null);
      setSelectedMetric(null);
      setNotice("");
      setError("");
      setActivePage("Dashboard");
    }
  }

  async function switchAccount(userId) {
    if (!userId || accountSwitching) return;
    setAccountSwitching(true);
    setError("");
    setMessages([]);
    setQuestion("");
    setSelectedCategory(null);
    setSelectedMetric(null);
    setSelectedTimelineDate(null);
    setNotice("");
    try {
      const response = await fetch(`${API}/auth/switch-account`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ user_id: userId }),
      });
      const result = await readApiResponse(response);
      if (!response.ok) throw new Error(result.detail || "Could not switch accounts.");
      await finishSignIn(result.account);
    } catch (switchError) {
      setError(switchError.message);
    } finally {
      setAccountSwitching(false);
    }
  }

  async function addAccount() {
    setError("");
    try {
      const response = await fetch(`${API}/auth/add-account`, {
        method: "POST",
        credentials: "include",
      });
      const result = await readApiResponse(response);
      if (!response.ok) throw new Error(result.detail || "Could not add another account.");
      setAccount(null);
      setStatements([]);
      setBankAccounts([]);
      setDashboardSelectionData(null);
      setCombinedData(null);
      setActiveStatementId(null);
      setMessages([]);
      setQuestion("");
      setSelectedCategory(null);
      setSelectedMetric(null);
      setSelectedTimelineDate(null);
      setNotice("");
      setRememberedAccounts([]);
      setAuthNotice("Sign in to add another account to this device. Your current account will stay remembered.");
    } catch (addError) {
      setError(addError.message);
    }
  }

  useEffect(() => {
    async function restoreSession() {
      try {
        const response = await fetch(`${API}/auth/me`, { credentials: "include" });
        if (!response.ok) return;
        const profile = await readApiResponse(response);
        setAccount(profile);
        const accountsResponse = await fetch(`${API}/auth/accounts`, { credentials: "include" });
        if (accountsResponse.ok) {
          const accountsResult = await readApiResponse(accountsResponse);
          setRememberedAccounts(Array.isArray(accountsResult.accounts) ? accountsResult.accounts : []);
        }
        const historyResponse = await fetch(`${API}/statements`, { credentials: "include" });
        if (!historyResponse.ok) return;
        const historyResult = await readApiResponse(historyResponse);
        const history = Array.isArray(historyResult.statements) ? historyResult.statements : [];
        setStatements(history);
        const bankAccountsResponse = await fetch(`${API}/bank-accounts`, { credentials: "include" });
        if (bankAccountsResponse.ok) {
          const bankAccountsResult = await readApiResponse(bankAccountsResponse);
          setBankAccounts(Array.isArray(bankAccountsResult.bank_accounts) ? bankAccountsResult.bank_accounts : []);
        }
        if (history.length > 0) {
          const statementResponse = await fetch(
            `${API}/statements/${history[0].statement_id}`,
            { credentials: "include" }
          );
          if (statementResponse.ok) {
            const statementResult = await readApiResponse(statementResponse);
            setActiveStatementId(statementResult.statement_id ?? history[0].statement_id);
          }
        }
      } catch (restoreError) {
        console.error("Could not restore Stack Up session.", restoreError);
      } finally {
        setAuthLoading(false);
      }
    }
    restoreSession();
  }, []);

  useEffect(() => {
    if (activePage === "AI Assistant") {
      chatInputRef.current?.focus();
    }
  }, [activePage]);

  function openAssistant() {
    setActivePage("AI Assistant");
    setMobileMenu(false);
  }

  function openMetric(metric) {
    setSelectedMetric(metric);
    setSelectedCategory(null);
    setActivePage("Analytics");
  }

  async function updateCategory(transaction, category) {
    setError("");
    try {
      const response = await fetch(
        `${API}/transactions/${transaction.id}/category`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ category }),
        }
      );
      const result = await readApiResponse(response);
      if (!response.ok || result.status !== "success") {
        throw new Error(result.message || "Could not update this category.");
      }
      setCombinedRefreshKey((current) => current + 1);
      setNotice(
        result.updated_count > 1
          ? `Category saved as ${category} for ${result.updated_count} transactions to ${result.counterparty}.`
          : `Category saved as ${category}.`
      );
    } catch (err) {
      setError(err.message);
    }
  }

  async function toggleIncomeInclusion(transaction, included) {
    setIncomeInclusionBusyId(transaction.id);
    setError("");
    try {
      const response = await fetch(
        `${API}/transactions/${transaction.id}/income-inclusion`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ included }),
        }
      );
      const result = await readApiResponse(response);
      if (!response.ok || result.status !== "success") {
        throw new Error(result.detail || "Could not update this income choice.");
      }
      setCombinedRefreshKey((current) => current + 1);
      setNotice(
        included
          ? "UPI credit added to income."
          : "UPI credit removed from income."
      );
    } catch (incomeError) {
      setError(incomeError.message);
    } finally {
      setIncomeInclusionBusyId(null);
    }
  }

  function splitSharedBillEvenly() {
    const transaction = shareableTransactions.find(
      (item) => String(item.id) === sharedBillTransactionId
    );
    if (!transaction || !sharedBillParticipants.length) return;
    const totalCents = Math.round(getAmount(transaction) * 100);
    const otherShareCents = Math.floor(
      totalCents / (sharedBillParticipants.length + 1)
    );
    const ownerShareCents = totalCents - (
      otherShareCents * sharedBillParticipants.length
    );
    setSharedBillOwnerShare((ownerShareCents / 100).toFixed(2));
    setSharedBillParticipants((current) => current.map((participant) => ({
      ...participant,
      share_amount: (otherShareCents / 100).toFixed(2),
    })));
  }

  async function createSharedBill(event) {
    event.preventDefault();
    setSharedBillBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/shared-bills`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transaction_id: Number(sharedBillTransactionId),
          title: sharedBillTitle,
          owner_share: Number(sharedBillOwnerShare),
          participants: sharedBillParticipants.map((participant) => ({
            name: participant.name,
            share_amount: Number(participant.share_amount),
          })),
        }),
      });
      const result = await readApiResponse(response);
      if (!response.ok) {
        throw new Error(result.detail || "Could not save this shared bill.");
      }
      setSharedBills(result.shared_bills ?? []);
      setSharedBillRefreshKey((current) => current + 1);
      setCombinedRefreshKey((current) => current + 1);
      setSharedBillFormOpen(false);
      setSharedBillTransactionId("");
      setSharedBillTitle("");
      setSharedBillOwnerShare("");
      setSharedBillParticipants([{ name: "", share_amount: "" }]);
      setNotice("Shared bill saved. Your expenses now use your share.");
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSharedBillBusy(false);
    }
  }

  async function setSharedBillRepaid(billId, participantId, isPaid) {
    try {
      const response = await fetch(
        `${API}/shared-bills/${billId}/participants/${participantId}`,
        {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_paid: isPaid }),
        }
      );
      const result = await readApiResponse(response);
      if (!response.ok) {
        throw new Error(result.detail || "Could not update repayment status.");
      }
      setSharedBills(result.shared_bills ?? []);
      setNotice(isPaid ? "Repayment marked as received." : "Repayment marked as outstanding.");
    } catch (repaymentError) {
      setError(repaymentError.message);
    }
  }

  async function deleteSharedBill(bill) {
    if (!window.confirm(`Remove shared-bill tracking for "${bill.title}"? The transaction remains in your statement.`)) {
      return;
    }
    try {
      const response = await fetch(`${API}/shared-bills/${bill.id}`, {
        method: "DELETE",
        credentials: "include",
      });
      const result = await readApiResponse(response);
      if (!response.ok) {
        throw new Error(result.detail || "Could not remove shared-bill tracking.");
      }
      setSharedBills(result.shared_bills ?? []);
      setCombinedRefreshKey((current) => current + 1);
      setNotice("Shared-bill tracking removed. The full transaction is counted as an expense again.");
    } catch (deleteError) {
      setError(deleteError.message);
    }
  }

  async function uploadStatement(event) {
    const file = event.target.files?.[0];
    event.target.value = "";

    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Please select a PDF bank statement.");
      return;
    }

    setUploading(true);
    setError("");
    setNotice("Uploading and analyzing your statement...");

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (uploadBankAccountId) formData.append("bank_account_id", uploadBankAccountId);

      const response = await fetch(
        `${API}/upload-statement?reprocess=true`,
        {
          method: "POST",
          credentials: "include",
          body: formData,
        }
      );

      const result = await readApiResponse(response);

      if (!response.ok) {
        throw new Error(result.detail || "Upload failed.");
      }

      if (result.status === "duplicate") {
        if (result.statement_id != null) {
          setActiveStatementId(result.statement_id);
          setAiStatementIds([result.statement_id]);
          setMessages([]);
        }
        setSelectedDashboardStatementIds(null);
        await refreshStatementHistory();
        setNotice(result.message || "This statement was already uploaded.");
        return;
      }

      if (result.status !== "success") {
        throw new Error(result.message || result.error || "Unable to analyze this PDF.");
      }

      setActiveStatementId(result.statement_id ?? null);
      setAiStatementIds(result.statement_id != null ? [result.statement_id] : []);
      setSelectedDashboardStatementIds(null);
      setMessages([]);
      try {
        await refreshStatementHistory();
      } catch (historyError) {
        console.error("Statement uploaded but history refresh failed.", historyError);
      }
      setNotice(
        `Statement analyzed successfully! ${result.transaction_count ?? result.transactions?.length ?? 0} transactions processed.`
      );
      setActivePage("Dashboard");
    } catch (err) {
      setError(
        `${err.message}. Check that the backend is running at ${API}.`
      );
      setNotice("");
    } finally {
      setUploading(false);
    }
  }

  async function askQuestion(text) {
    if (!text || asking) return;
    if (statements.length > 0 && aiStatementIds.length === 0) {
      setError("Select at least one statement for the AI assistant.");
      return;
    }

    setMessages((previous) => [...previous, { role: "user", text }]);
    setQuestion("");
    setAsking(true);
    setError("");

    try {
      const history = messages
        .slice(-12)
        .filter((message) => ["user", "assistant"].includes(message.role))
        .map(({ role, text: messageText }) => ({ role, text: messageText }));
      const params = new URLSearchParams({
        message: text,
      });
      aiStatementIds.forEach((statementId) => params.append("statement_ids", String(statementId)));

      const response = await fetch(`${API}/message?${params.toString()}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ history }),
      });

      const result = await readApiResponse(response);

      if (!response.ok) {
        throw new Error(result.detail || "The assistant request failed.");
      }

      const reply =
        result.message ??
        result.response ??
        result.answer ??
        (typeof result === "string" ? result : JSON.stringify(result, null, 2));

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          text: String(reply),
          category: result.category,
          transactions: Array.isArray(result.transactions) ? result.transactions : null,
          suggestions: Array.isArray(result.suggestions) ? result.suggestions : null,
          followUps: getFollowUpQuestions(result, text),
        },
      ]);
    } catch (err) {
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          text: `I couldn't connect to the assistant. ${err.message}`,
        },
      ]);
    } finally {
      setAsking(false);
    }
  }

  async function deleteStatement(statement) {
    const statementId = statement.statement_id;
    const filename = statement.filename || "this statement";
    if (!window.confirm(`Delete ${filename} and its saved transactions? This cannot be undone.`)) return;

    try {
      const response = await fetch(`${API}/statements/${statementId}`, {
        method: "DELETE",
        credentials: "include",
      });
      const result = await readApiResponse(response);
      if (!response.ok) throw new Error(result.detail || "Could not delete this statement.");

      const remaining = await refreshStatementHistory();
      setAiStatementIds((current) => current.filter((id) => id !== statementId));
      if (activeStatementId === statementId) {
        if (remaining.length > 0) {
          await loadSavedStatement(remaining[0].statement_id);
        } else {
          setActiveStatementId(null);
          setMessages([]);
        }
      }
      setNotice(`${filename} deleted from statement history.`);
      setError("");
    } catch (deleteError) {
      setError(deleteError.message);
    }
  }

  function sendQuestion(event) {
    event.preventDefault();
    askQuestion(question.trim());
  }

  const dashboardSelectionIds = selectedDashboardStatementIds
    ?? statements.map((statement) => statement.statement_id);
  const useCombinedScope = selectedDashboardStatementIds === null && statements.length > 0;
  const hasMultipleDashboardStatements = dashboardSelectionIds.length > 1;
  const allDashboardStatementsSelected = statements.length > 0
    && dashboardSelectionIds.length === statements.length;
  const dashboardScopeDescription = useCombinedScope
    ? "all uploaded statements"
    : `${dashboardSelectionIds.length} selected statement${dashboardSelectionIds.length === 1 ? "" : "s"}`;
  const statementGroups = [
    ...bankAccounts.map((bankAccount) => ({
      id: bankAccount.id,
      name: bankAccount.name,
      statements: statements.filter((statement) => statement.bank_account_id === bankAccount.id),
    })),
    {
      id: "unassigned",
      name: "Unassigned statements",
      statements: statements.filter((statement) => !statement.bank_account_id),
    },
  ].filter((group) => group.statements.length > 0 || group.id !== "unassigned");
  const displayTransactions = useCombinedScope
    ? combinedData?.transactions ?? []
    : dashboardSelectionData?.transactions ?? [];
  const sharedBillTransactionIds = new Set(
    sharedBills.map((bill) => Number(bill.transaction_id))
  );
  const shareableTransactions = displayTransactions.filter((transaction) =>
    String(transaction.type ?? "").toLowerCase() === "debit" &&
    String(transaction.transaction_type ?? "").toLowerCase() === "expense" &&
    !isUpiActivity(transaction, "received") &&
    !isUpiActivity(transaction, "sent") &&
    transaction.shared_bill_id == null &&
    !sharedBillTransactionIds.has(Number(transaction.id))
  );
  const selectedSharedBillTransaction = shareableTransactions.find(
    (transaction) => String(transaction.id) === sharedBillTransactionId
  );
  const visibleSharedBills = sharedBills.filter((bill) =>
    displayTransactions.some(
      (transaction) => Number(transaction.id) === Number(bill.transaction_id)
    )
  );
  const displayAnalysis = useCombinedScope
    ? combinedData?.analysis ?? null
    : dashboardSelectionData?.analysis ?? null;
  const totalIncome = Number(displayAnalysis?.total_income ?? 0);
  const totalExpenses = Number(displayAnalysis?.total_expenses ?? 0);
  const totalUpiReceived = Number(displayAnalysis?.total_upi_received ?? 0);
  const totalUpiSent = Number(displayAnalysis?.total_upi_sent ?? 0);
  const netCashFlow = Number(
    displayAnalysis?.net_cash_flow ?? totalIncome - totalExpenses
  );
  const savingsRate = Number(
    displayAnalysis?.savings_rate ??
      (totalIncome > 0 ? (netCashFlow / totalIncome) * 100 : 0)
  );
  const plannedSavings = Number(savingsGoals[savingsAccountKey] || 0);
  const hasSavingsGoal = Object.prototype.hasOwnProperty.call(
    savingsGoals,
    savingsAccountKey
  );
  const firstTransaction = displayTransactions[0];
  const firstBankDirection = String(firstTransaction?.type ?? "").toLowerCase();
  const firstCategory = firstTransaction ? getAnalyticsCategory(firstTransaction) : "";
  const firstDirection = firstBankDirection === "credit" || firstCategory === "UPI Received"
    || String(firstTransaction?.transaction_type ?? "").toLowerCase() === "income"
    ? "credit"
    : firstBankDirection === "debit" || firstCategory === "UPI Sent"
      || String(firstTransaction?.transaction_type ?? "").toLowerCase() === "expense"
      ? "debit"
      : "unknown";
  const firstBalance = Number(firstTransaction?.balance);
  const firstAmount = getAmount(firstTransaction || {});
  const openingBalance = firstTransaction
    && Number.isFinite(firstBalance)
    && firstDirection !== "unknown"
    ? firstBalance - (firstDirection === "credit" ? firstAmount : -firstAmount)
    : null;
  const totalIncomingToAccount = displayTransactions.reduce((total, transaction) => {
    const bankDirection = String(transaction.type ?? "").toLowerCase();
    const transactionType = String(transaction.transaction_type ?? "").toLowerCase();
    const category = getAnalyticsCategory(transaction);
    if (bankDirection === "credit") return total + getAmount(transaction);
    if (bankDirection === "debit") return total;
    if (transactionType === "income" || category === "UPI Received") {
      return total + getAmount(transaction);
    }
    return total;
  }, 0);
  const totalFundsAvailable = Math.max(0, (openingBalance ?? 0) + totalIncomingToAccount);
  const spendingLimit = Math.max(0, totalFundsAvailable - plannedSavings);
  const totalOutgoingFromAccount = displayTransactions.reduce((total, transaction) => {
    const bankDirection = String(transaction.type ?? "").toLowerCase();
    const transactionType = String(transaction.transaction_type ?? "").toLowerCase();
    const category = getAnalyticsCategory(transaction);
    if (bankDirection === "debit") return total + getAmount(transaction);
    if (bankDirection === "credit") return total;
    if (transactionType === "expense" || category === "UPI Sent") {
      return total + getAmount(transaction);
    }
    return total;
  }, 0);
  const limitUsagePercent = spendingLimit > 0
    ? (totalOutgoingFromAccount / spendingLimit) * 100
    : totalOutgoingFromAccount > 0 ? 100 : 0;
  const limitIntensity = limitUsagePercent < 50
    ? "low"
    : limitUsagePercent < 85 ? "medium" : "hard";
  const remainingSpendingLimit = spendingLimit - totalOutgoingFromAccount;

  function saveSavingsGoal(event) {
    event.preventDefault();
    const goal = Number(savingsGoalDraft);
    if (!Number.isFinite(goal) || goal < 0) {
      setSavingsGoalError("Enter a valid savings amount.");
      return;
    }
    if (goal > totalFundsAvailable) {
      setSavingsGoalError("Your savings goal cannot be greater than the total funds available.");
      return;
    }
    setSavingsGoals((current) => ({ ...current, [savingsAccountKey]: goal }));
    setSavingsGoalDraft(String(goal));
    setSavingsGoalError("");
  }

  const hasRealData = Boolean(displayAnalysis);
  const recentTransactions = [...displayTransactions]
    .sort((a, b) => {
      const dateA = getTransactionDateKey(a.date ?? a.transaction_date);
      const dateB = getTransactionDateKey(b.date ?? b.transaction_date);
      if (dateA === "Unknown date") return 1;
      if (dateB === "Unknown date") return -1;
      return dateB.localeCompare(dateA);
    })
    .slice(0, 5);
  const normalizedSearch = searchQuery.trim().toLocaleLowerCase();
  const transactionCategoryOptions = [...new Set(
    displayTransactions.map(getTransactionCategory)
  )].sort((a, b) => a.localeCompare(b));
  const transactionFiltersActive = Object.values(transactionFilters).some(
    (value) => value !== "" && value !== "all"
  );
  const filteredTransactions = displayTransactions.filter((transaction) => {
    const category = getTransactionCategory(transaction);
    const type = getTransactionFilterType(transaction);
    const date = getTransactionDateKey(transaction.date ?? transaction.transaction_date);
    const amount = getAmount(transaction);
    const matchesFilters =
      (transactionFilters.category === "all" || category === transactionFilters.category) &&
      (transactionFilters.type === "all" || type === transactionFilters.type) &&
      (!transactionFilters.fromDate || (date !== "Unknown date" && date >= transactionFilters.fromDate)) &&
      (!transactionFilters.toDate || (date !== "Unknown date" && date <= transactionFilters.toDate)) &&
      (transactionFilters.minAmount === "" || amount >= Number(transactionFilters.minAmount)) &&
      (transactionFilters.maxAmount === "" || amount <= Number(transactionFilters.maxAmount));

    if (!matchesFilters) return false;
    if (normalizedSearch) {
        const searchableText = [
          getTransactionName(transaction),
          category,
          transaction.description,
          transaction.merchant,
          transaction.narration,
          transaction.type,
          transaction.transaction_type,
          transaction.date,
          transaction.transaction_date,
          formatDate(transaction.date ?? transaction.transaction_date),
          amount,
          money(amount),
        ]
          .filter(Boolean)
          .join(" ")
          .toLocaleLowerCase();
        return searchableText.includes(normalizedSearch);
    }
    return true;
  });

  const timelineByDate = new Map();
  displayTransactions.forEach((transaction) => {
    const dateKey = getTransactionDateKey(
      transaction.date ?? transaction.transaction_date
    );
    const daily = timelineByDate.get(dateKey) ?? {
      dateKey,
      income: 0,
      expenses: 0,
      count: 0,
    };
    const amount = getAmount(transaction);
    if (!isUpiActivity(transaction, "received") && !isUpiActivity(transaction, "sent")) {
      if (getAmountDirection(transaction) === "income") daily.income += amount;
      else daily.expenses += amount;
    }
    daily.count += 1;
    timelineByDate.set(dateKey, daily);
  });
  const transactionTimeline = [...timelineByDate.values()].sort((a, b) => {
    if (a.dateKey === "Unknown date") return 1;
    if (b.dateKey === "Unknown date") return -1;
    return a.dateKey.localeCompare(b.dateKey);
  });
  const maxDailyAmount = Math.max(
    0,
    ...transactionTimeline.flatMap((day) => [day.income, day.expenses])
  );
  const timelineIncome = transactionTimeline.reduce((sum, day) => sum + day.income, 0);
  const timelineExpenses = transactionTimeline.reduce((sum, day) => sum + day.expenses, 0);
  const dateSortedTransactions = [...displayTransactions].sort((a, b) => {
    const dateA = getTransactionDateKey(a.date ?? a.transaction_date);
    const dateB = getTransactionDateKey(b.date ?? b.transaction_date);
    if (dateA === "Unknown date") return 1;
    if (dateB === "Unknown date") return -1;
    return dateB.localeCompare(dateA);
  });
  const selectedTimelineDay = transactionTimeline.find(
    (day) => day.dateKey === selectedTimelineDate
  );
  const selectedDateTransactions = selectedTimelineDay
    ? displayTransactions.filter((transaction) =>
        getTransactionDateKey(transaction.date ?? transaction.transaction_date) === selectedTimelineDate
      )
    : [];

  const spendingEntries = Object.entries(displayAnalysis?.category_totals ?? {})
    .filter(([category]) => !/income|salary|credit|deposit/i.test(category))
    .map(([label, amount]) => ({
      label,
      amount: Math.abs(Number(amount) || 0),
    }))
    .sort((a, b) => b.amount - a.amount)
    .slice(0, 5);

  const categoryOverview = displayTransactions.reduce((categories, transaction) => {
    const label = getAnalyticsCategory(transaction);
    const category = categories.get(label) ?? { label, amount: 0, count: 0 };
    const isExpense = String(transaction.transaction_type ?? "").toLowerCase() === "expense";
    category.amount += isExpense
      ? getCountedExpenseAmount(transaction)
      : getAmount(transaction);
    category.count += 1;
    categories.set(label, category);
    return categories;
  }, new Map());
  // Keep these useful buckets visible even when the current statement has no
  // matching rows yet, so users can still open them and see an empty state.
  ["Other", "UPI Sent", "UPI Received"].forEach((label) => {
    if (!categoryOverview.has(label)) {
      categoryOverview.set(label, { label, amount: 0, count: 0 });
    }
  });
  const allCategoryEntries = [...categoryOverview.values()]
    .sort((a, b) => b.amount - a.amount);
  const allCategoryTotal = allCategoryEntries.reduce((sum, item) => sum + item.amount, 0);

  const selectedCategoryTransactions = selectedCategory
    ? displayTransactions.filter((transaction) =>
        getAnalyticsCategory(transaction) === selectedCategory
      )
    : [];

  const incomeTransactions = displayTransactions.filter(
    (transaction) =>
      !isUpiActivity(transaction, "sent") &&
      (
        (
          isUpiActivity(transaction, "received") &&
          transaction.income_included
        ) ||
        (
          !isUpiActivity(transaction, "received") &&
          String(getAnalyticsCategory(transaction)).trim().toLowerCase() !== "transfer" &&
          String(transaction.transaction_type ?? "").toLowerCase() === "income"
        )
      )
  );
  const upiReceivedTransactions = displayTransactions.filter(
    (transaction) =>
      isUpiActivity(transaction, "received") &&
      String(transaction.type ?? "").toLowerCase() === "credit"
  );
  const expenseTransactions = displayTransactions.filter(
    (transaction) =>
      !isUpiActivity(transaction, "received") &&
      !isUpiActivity(transaction, "sent") &&
      (
        String(transaction.transaction_type ?? "").toLowerCase() === "expense" ||
        (
          String(transaction.transaction_type ?? "").toLowerCase() === "transfer" &&
          String(transaction.type ?? "").toLowerCase() === "debit"
        )
      )
  );
  const selectedMetricTransactions = selectedMetric === "total_income"
    ? incomeTransactions
    : selectedMetric === "total_expenses"
      ? expenseTransactions
      : [...incomeTransactions, ...expenseTransactions].sort(
          (a, b) => (b.id ?? 0) - (a.id ?? 0)
        );
  const metricCategoryOptions = [...new Set(
    selectedMetricTransactions.map(getAnalyticsCategory)
  )].sort((a, b) => a.localeCompare(b));
  const filteredMetricTransactions = selectedMetricTransactions.filter((transaction) => {
    const category = getAnalyticsCategory(transaction);
    const type = String(
      transaction.income_included
        ? "income"
        : transaction.transaction_type || getTransactionType(transaction)
    ).toLowerCase();
    const date = getTransactionDateKey(transaction.date ?? transaction.transaction_date);
    const amount = getAmount(transaction);
    return (
      (metricFilters.category === "all" || category === metricFilters.category) &&
      (metricFilters.type === "all" || type === metricFilters.type) &&
      (!metricFilters.fromDate || (date !== "Unknown date" && date >= metricFilters.fromDate)) &&
      (!metricFilters.toDate || (date !== "Unknown date" && date <= metricFilters.toDate)) &&
      (metricFilters.minAmount === "" || amount >= Number(metricFilters.minAmount)) &&
      (metricFilters.maxAmount === "" || amount <= Number(metricFilters.maxAmount))
    );
  });
  const metricFiltersActive = Object.values(metricFilters).some(
    (value) => value !== "" && value !== "all"
  );

  const metricDetails = {
    net_cash_flow: {
      title: "Net cash flow",
      value: money(netCashFlow),
      formula: `${money(totalIncome)} total income - ${money(totalExpenses)} total expenses = ${money(netCashFlow)}`,
      explanation: `Calculated from ${incomeTransactions.length} income transactions and ${expenseTransactions.length} expenses/outgoing non-UPI transfers. UPI activity and unknown transactions are excluded.`,
    },
    total_income: {
      title: "Total income",
      value: money(totalIncome),
      formula: `Sum of ${incomeTransactions.length} income transactions, including any UPI credits you selected = ${money(totalIncome)}`,
      explanation: "UPI Received credits are separate by default. Use the checkboxes below to include selected credits in income.",
    },
    total_expenses: {
      title: "Total expenses",
      value: money(totalExpenses),
      formula: `Sum of ${expenseTransactions.length} expenses and outgoing non-UPI transfers = ${money(totalExpenses)}`,
      explanation: "Expenses and outgoing non-UPI transfers are included. UPI Sent and UPI Received are tracked separately.",
    },
    savings_rate: {
      title: "Savings rate",
      value: `${savingsRate.toFixed(1)}%`,
      formula: totalIncome > 0
        ? `(${money(totalIncome)} income - ${money(totalExpenses)} expenses) / ${money(totalIncome)} income = ${savingsRate.toFixed(1)}%`
        : "Savings rate is 0% because there is no income recorded.",
      explanation: `Uses ${incomeTransactions.length} income transactions and ${expenseTransactions.length} expenses/outgoing non-UPI transfers. UPI activity and unknown transactions are excluded.`,
    },
  };
  const metricDetail = selectedMetric ? metricDetails[selectedMetric] : null;

  const spendingTotal = spendingEntries.reduce(
    (sum, item) => sum + item.amount,
    0
  );

  const accountLabel = account?.username || account?.email || account?.phone || "Personal account";

  if (authLoading) {
    return <main className="auth-screen"><div className="auth-loading">Loading your account...</div></main>;
  }

  if (!account) {
    return <AuthScreen onAuthenticated={finishSignIn} initialNotice={authNotice} />;
  }

  return (
    <div className="app-layout">
      <aside className={`sidebar ${mobileMenu ? "sidebar-open" : ""}`}>
        <a
          className="brand"
          href="#"
          onClick={(event) => {
            event.preventDefault();
            setActivePage("Dashboard");
            setMobileMenu(false);
          }}
        >
          <img className="brand-image" src={theme === "light" ? stackUpLightLogo : stackUpLogo} alt="Stack Up Personal Finance" />
        </a>

        <div className="workspace-label">SERVICES</div>

        <nav className="navigation">
          {navigation.map(({ label, icon: Icon }) => (
            <button
              key={label}
              className={`nav-item ${activePage === label ? "nav-active" : ""}`}
              onClick={() => {
                if (label === "AI Assistant") {
                  openAssistant();
                } else {
                  if (label === "Analytics") {
                    setSelectedMetric(null);
                    setSelectedCategory(null);
                  }
                  setActivePage(label);
                }
                setMobileMenu(false);
              }}
            >
              <Icon size={19} strokeWidth={1.8} />
              <span>{label}</span>
              {label === "AI Assistant" && <span className="ai-dot" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="upgrade-card">
            <span className="upgrade-icon"><Sparkles size={18} /></span>
            <strong>Your money, smarter.</strong>
            <p>Understand your spending and make every rupee count.</p>
            <button onClick={openAssistant}>
              Explore AI <ArrowUpRight size={15} />
            </button>
          </div>

          <details className="sidebar-account-menu">
            <summary className="profile" aria-label="Open account options">
              <div className="avatar">{accountLabel.slice(0, 1).toUpperCase()}</div>
              <div className="profile-text">
                <strong>{accountLabel}</strong>
                <span>Personal account</span>
              </div>
              <span className="online-dot" />
            </summary>
            <div className="sidebar-account-dropdown">
              <button
                className="settings-menu-button"
                type="button"
                onClick={(event) => {
                  setActivePage("Account Settings");
                  setMobileMenu(false);
                  event.currentTarget.closest("details")?.removeAttribute("open");
                }}
              >
                <Settings size={15} />
                <span>Account settings</span>
              </button>
              <span className="sidebar-account-label">ACCOUNTS ON THIS DEVICE</span>
              <div className="remembered-account-list">
                {rememberedAccounts.map((savedAccount) => {
                  const label = savedAccount.username || savedAccount.email || savedAccount.phone || "Personal account";
                  return savedAccount.active ? (
                    <div className="remembered-account current" key={savedAccount.user_id}>
                      <span>{label}</span>
                      <small>Current</small>
                    </div>
                  ) : (
                    <button
                      className="remembered-account"
                      type="button"
                      key={savedAccount.user_id}
                      disabled={accountSwitching}
                      onClick={() => switchAccount(savedAccount.user_id)}
                    >
                      <span>{label}</span>
                      <small>{accountSwitching ? "Switching..." : "Switch"}</small>
                    </button>
                  );
                })}
              </div>
              <button className="add-remembered-account" type="button" onClick={addAccount}>
                <ArrowLeftRight size={15} />
                <span>Add another account</span>
              </button>
            </div>
          </details>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <button
            className="icon-button mobile-menu-button"
            onClick={() => setMobileMenu(!mobileMenu)}
            aria-label="Toggle menu"
          >
            <Menu size={21} />
          </button>

          <div className="breadcrumb">
            Workspace <span>/</span> <strong>{activePage}</strong>
          </div>

          <div className="topbar-actions">
            <div className="search-box">
              <Search size={17} />
              <input
                placeholder="Search transactions..."
                aria-label="Search transactions"
                value={searchQuery}
                onChange={(event) => {
                  const value = event.target.value;
                  setSearchQuery(value);
                  if (value.trim()) setActivePage("Transactions");
                }}
              />
            </div>
            <details className="account-menu">
              <summary className="account-chip" title="Account options">
                <span className="account-chip-initial" aria-hidden="true">
                  {accountLabel.slice(0, 1).toUpperCase()}
                </span>
                <span className="account-chip-name">{accountLabel}</span>
              </summary>
              <div className="account-dropdown">
                <span className="account-dropdown-label">Signed in as</span>
                <strong className="account-dropdown-name">{accountLabel}</strong>
                <button
                  className="settings-menu-button"
                  type="button"
                  onClick={(event) => {
                    setActivePage("Account Settings");
                    event.currentTarget.closest("details")?.removeAttribute("open");
                  }}
                >
                  <Settings size={15} />
                  <span>Account settings</span>
                </button>
                <button className="account-logout" onClick={signOut}>
                  <LogOut size={16} />
                  <span>Log out</span>
                </button>
              </div>
            </details>
          </div>
        </header>

        <div className="page-container">
          {notice && (
            <div className="notice-message" role="status">
              {notice}
              <button onClick={() => setNotice("")} aria-label="Dismiss">×</button>
            </div>
          )}

          {error && (
            <div className="error-message" role="alert">
              {error}
              <button onClick={() => setError("")} aria-label="Dismiss">×</button>
            </div>
          )}

          {activePage === "Account Settings" && (
            <AccountSettings
              account={account}
              theme={theme}
              setTheme={setTheme}
              onProfileUpdated={setAccount}
              onDeleted={() => {
                try {
                  window.localStorage.removeItem(`stackup:theme:${savingsAccountKey}`);
                } catch {
                  // Local appearance data is nonessential to server-side account deletion.
                }
                setSavingsGoals((current) => {
                  const next = { ...current };
                  delete next[savingsAccountKey];
                  return next;
                });
                setAccount(null);
                setRememberedAccounts([]);
                setMessages([]);
                setQuestion("");
                setStatements([]);
                setBankAccounts([]);
                setSelectedDashboardStatementIds(null);
                setCombinedData(null);
                setAiStatementIds([]);
                setActivePage("Dashboard");
              }}
            />
          )}

          {activePage === "Dashboard" && (
            <>
              <section className="welcome-row">
                <div>
                  <div className="eyebrow">
                    <span className="live-dot" /> YOUR FINANCIAL OVERVIEW
                  </div>
                  <h1>Your money, <span>in focus.</span></h1>
                  <p className="page-subtitle">
                    {hasRealData
                      ? useCombinedScope
                        ? `Combined view of ${combinedData?.statementCount ?? statements.length} uploaded statements. Overlapping transactions are counted once.`
                        : `Calculated from ${dashboardScopeDescription}. Overlapping transactions are counted once.`
                      : "Upload a bank statement to see your financial overview."}
                  </p>
                  {hasMultipleDashboardStatements && (
                    <p className="demo-note">
                      Transfers between your own accounts may need category review if
                      the statements do not identify them as transfers.
                    </p>
                  )}
                </div>

                <div className="welcome-actions">
                  {(statements.length > 0 || bankAccounts.length > 0) && (
                    <details className="dashboard-statement-picker">
                      <summary>
                        <span>Select statements</span>
                        <strong>{dashboardSelectionIds.length} of {statements.length} selected</strong>
                      </summary>
                      <div className="dashboard-statement-picker-panel">
                        {statements.length > 0 && (
                          <label className="statement-select-all">
                            <input
                              type="checkbox"
                              checked={allDashboardStatementsSelected}
                              onChange={(event) => setSelectedDashboardStatementIds(
                                event.target.checked ? null : []
                              )}
                            />
                            <strong>Select all statements</strong>
                          </label>
                        )}
                        {statementGroups.map((group) => (
                          <section className="statement-bank-group" key={group.id}>
                            <label className="statement-bank-group-heading">
                              {group.statements.length > 0 && (
                                <input
                                  type="checkbox"
                                  checked={group.statements.every((statement) => dashboardSelectionIds.includes(statement.statement_id))}
                                  onChange={(event) => toggleDashboardStatementGroup(group.statements, event.target.checked)}
                                />
                              )}
                              <strong>{group.name}</strong>
                            </label>
                            {group.statements.length > 0 ? group.statements.map((statement) => (
                              <div className="dashboard-statement-option" key={statement.statement_id}>
                                <label>
                                  <input
                                    type="checkbox"
                                    checked={dashboardSelectionIds.includes(statement.statement_id)}
                                    onChange={() => selectDashboardStatement(String(statement.statement_id))}
                                  />
                                  <span>
                                    <strong>{statement.filename || "Bank statement"}</strong>
                                    <small>{formatDate(statement.created_at)} · {statement.transaction_count} transactions</small>
                                  </span>
                                </label>
                                <select
                                  aria-label={`Bank account for ${statement.filename || "statement"}`}
                                  value={statement.bank_account_id ?? ""}
                                  onChange={(event) => assignStatementToBankAccount(statement.statement_id, event.target.value)}
                                >
                                  <option value="">Unassigned</option>
                                  {bankAccounts.map((bankAccount) => (
                                    <option key={bankAccount.id} value={bankAccount.id}>{bankAccount.name}</option>
                                  ))}
                                </select>
                              </div>
                            )) : <p className="statement-group-empty">No statements assigned yet.</p>}
                          </section>
                        ))}
                        <form className="add-bank-account-form" onSubmit={createBankAccount}>
                          <input
                            value={bankAccountDraft}
                            onChange={(event) => setBankAccountDraft(event.target.value)}
                            maxLength={80}
                            placeholder="Add a bank account name"
                            aria-label="New bank account name"
                          />
                          <button className="secondary-button" type="submit" disabled={!bankAccountDraft.trim()}>
                            Add account
                          </button>
                        </form>
                      </div>
                    </details>
                  )}
                  {bankAccounts.length > 0 && (
                    <label className="dashboard-scope-control upload-bank-account">
                      <span>Upload to bank account</span>
                      <select value={uploadBankAccountId} onChange={(event) => setUploadBankAccountId(event.target.value)}>
                        <option value="">Unassigned</option>
                        {bankAccounts.map((bankAccount) => (
                          <option key={bankAccount.id} value={bankAccount.id}>{bankAccount.name}</option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label className={`upload-button ${uploading ? "uploading" : ""}`}>
                    <Upload size={17} />
                    {uploading ? "Analyzing..." : "Upload statement"}
                    <input
                      type="file"
                      accept=".pdf,application/pdf"
                      disabled={uploading}
                      onChange={uploadStatement}
                    />
                  </label>
                </div>
              </section>

              {useCombinedScope && combinedLoading && (
                <div className="notice-message" role="status">Combining your uploaded statements...</div>
              )}
              {useCombinedScope && combinedError && (
                <div className="error-message" role="alert">
                  Could not load the combined overview: {combinedError}
                </div>
              )}
              {!useCombinedScope && dashboardSelectionLoading && (
                <div className="notice-message" role="status">
                  Calculating the selected statements...
                </div>
              )}

              <section className="stat-grid">
                <button className="stat-card balance-card metric-card" onClick={() => openMetric("net_cash_flow")}>
                  <div className="stat-heading">
                    <span>Net cash flow</span>
                    <span className="stat-icon"><Wallet size={19} /></span>
                  </div>
                  <div className="stat-value">
                    {hasRealData ? money(netCashFlow) : "—"}
                  </div>
                  <div className="stat-foot">
                    <span>
                      {hasRealData
                        ? hasMultipleDashboardStatements ? "Across selected statements" : "From selected statement"
                        : "Upload a statement"}
                    </span>
                  </div>
                  <div className="balance-decoration">
                    <i /><i /><i /><i /><i /><i /><i />
                  </div>
                </button>

                <button className="stat-card metric-card" onClick={() => openMetric("total_income")}>
                  <div className="stat-heading">
                    <span>Total income</span>
                    <span className="stat-icon green-icon"><ArrowDownRight size={19} /></span>
                  </div>
                  <div className="stat-value">
                    {hasRealData ? money(totalIncome) : "—"}
                  </div>
                  <div className="stat-foot">
                    <span>{hasRealData ? "Income credits + selected UPI" : "Awaiting data"}</span>
                  </div>
                  <div className="mini-bars income-bars">
                    <i /><i /><i /><i /><i /><i /><i /><i /><i /><i />
                  </div>
                </button>

                <button className="stat-card metric-card" onClick={() => openMetric("total_expenses")}>
                  <div className="stat-heading">
                    <span>Total expenses</span>
                    <span className="stat-icon orange-icon"><ArrowUpRight size={19} /></span>
                  </div>
                  <div className="stat-value">
                    {hasRealData ? money(totalExpenses) : "—"}
                  </div>
                  <div className="stat-foot">
                    <span>{hasRealData ? "Expenses + transfers (UPI separate)" : "Awaiting data"}</span>
                  </div>
                  <div className="mini-bars expense-bars">
                    <i /><i /><i /><i /><i /><i /><i /><i /><i /><i />
                  </div>
                </button>

                <button className="stat-card metric-card" onClick={() => openMetric("savings_rate")}>
                  <div className="stat-heading">
                    <span>Savings rate</span>
                    <span className="stat-icon purple-icon"><PiggyBank size={19} /></span>
                  </div>
                  <div className="stat-value">
                    {hasRealData ? `${savingsRate.toFixed(1)}%` : "—"}
                  </div>
                  <div className="stat-foot">
                    <span>{hasRealData ? "Calculated from analysis" : "Awaiting data"}</span>
                  </div>
                  <div className="savings-track">
                    <span style={{ width: `${Math.min(100, Math.max(0, savingsRate))}%` }} />
                  </div>
                </button>
              </section>

              <section className="panel upi-activity-panel">
                <div className="upi-activity-heading">
                  <h2>UPI activity</h2>
                  <p>UPI totals stay separate; selected received credits can also count as income.</p>
                </div>
                <div className="upi-activity-grid">
                  <article>
                    <span>UPI received</span>
                    <strong>{hasRealData ? money(totalUpiReceived) : "—"}</strong>
                  </article>
                  <article>
                    <span>UPI sent</span>
                    <strong>{hasRealData ? money(totalUpiSent) : "—"}</strong>
                  </article>
                </div>
              </section>

              {dashboardSelectionIds.length !== 1 ? (
                <section className="panel savings-limit-panel">
                  <h2>Spending limit</h2>
                  <p>
                    Select exactly one statement to set a spending limit. Opening
                    balances from multiple statements can overlap or belong to
                    different bank accounts, so they are not combined here.
                  </p>
                </section>
              ) : (
              <section className={`panel savings-limit-panel limit-${limitIntensity}`}>
                <div className="savings-limit-heading">
                  <div>
                    <div className="eyebrow"><span className="live-dot" /> SPENDING LIMITER</div>
                    <h2>Set your savings target</h2>
                    <p>Choose how much of this selected statement’s income you want to save. Stack Up calculates your spending limit.</p>
                  </div>
                  <span className={`limit-intensity-badge ${hasSavingsGoal ? limitIntensity : "unset"}`}>
                    {hasSavingsGoal ? `${limitIntensity} intensity` : "Set a target"}
                  </span>
                </div>

                <form className="savings-limit-form" onSubmit={saveSavingsGoal}>
                  <label>
                    <span>Opening balance + money received</span>
                    <strong>{hasRealData ? money(totalFundsAvailable) : "Upload a statement first"}</strong>
                  </label>
                  <label className="savings-goal-input">
                    <span>Plan to save</span>
                    <div>
                      <span>₹</span>
                      <input
                        type="number"
                        min="0"
                        max={totalFundsAvailable}
                        step="1"
                        inputMode="numeric"
                        placeholder="e.g. 10000"
                        value={savingsGoalDraft}
                        onChange={(event) => {
                          setSavingsGoalDraft(event.target.value);
                          setSavingsGoalError("");
                        }}
                        disabled={!hasRealData}
                      />
                    </div>
                  </label>
                  <button className="primary-button" type="submit" disabled={!hasRealData || !savingsAccountKey}>
                    Set limit
                  </button>
                </form>

                {savingsGoalError && <p className="savings-limit-error" role="alert">{savingsGoalError}</p>}

                {hasSavingsGoal && (
                  <div className="savings-limit-results">
                    <div className="savings-limit-stats">
                      <div><span>Spending limit</span><strong>{money(spendingLimit)}</strong></div>
                      <div><span>Spent or sent</span><strong>{money(totalOutgoingFromAccount)}</strong></div>
                      <div>
                        <span>{remainingSpendingLimit >= 0 ? "Limit remaining" : "Over limit"}</span>
                        <strong>{money(Math.abs(remainingSpendingLimit))}</strong>
                      </div>
                    </div>
                    <div
                      className="limit-progress-track"
                      role="progressbar"
                      aria-label="Spending limit used"
                      aria-valuemin="0"
                      aria-valuemax="100"
                      aria-valuenow={Math.min(100, Math.max(0, limitUsagePercent))}
                    >
                      <span style={{ width: `${Math.min(100, Math.max(0, limitUsagePercent))}%` }} />
                    </div>
                    <p className="limit-intensity-message">
                      <span className={`limit-traffic-light ${limitIntensity}`} aria-hidden="true" />
                      {remainingSpendingLimit < 0
                        ? `Hard: spending is ${money(Math.abs(remainingSpendingLimit))} over your limit.`
                        : `${limitIntensity[0].toUpperCase()}${limitIntensity.slice(1)}: ${limitUsagePercent.toFixed(0)}% of your spending limit used.`}
                    </p>
                    <p className="limit-spend-guidance">
                      {remainingSpendingLimit >= 0
                        ? `You can spend ${money(remainingSpendingLimit)} more and still keep ${money(plannedSavings)} toward your savings goal.`
                        : `You are ${money(Math.abs(remainingSpendingLimit))} over the limit. To still save ${money(plannedSavings)}, you need that much additional money or a lower savings goal.`}
                    </p>
                    <small>
                      {openingBalance === null
                        ? "Opening balance could not be determined from this statement. "
                        : `${money(openingBalance)} opening balance + `}
                      {money(totalIncomingToAccount)} received (including UPI Received) − {money(plannedSavings)} planned savings = {money(spendingLimit)} available to spend.
                    </small>
                  </div>
                )}
              </section>
              )}

              <section className="panel shared-bills-panel">
                <div className="panel-heading">
                  <div>
                    <div className="eyebrow"><span className="live-dot" /> SHARED EXPENSES</div>
                    <h2>Shared bills</h2>
                    <p>Your expense uses your share; the full bank payment and repayments stay visible.</p>
                  </div>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => setSharedBillFormOpen((open) => !open)}
                    disabled={!shareableTransactions.length && !sharedBillFormOpen}
                  >
                    <Plus size={15} /> {sharedBillFormOpen ? "Close" : "Add shared bill"}
                  </button>
                </div>

                {sharedBillFormOpen && (
                  <form className="shared-bill-form" onSubmit={createSharedBill}>
                    {shareableTransactions.length > 0 ? (
                      <>
                        <label>
                          <span>Expense transaction</span>
                          <select
                            value={sharedBillTransactionId}
                            onChange={(event) => {
                              const nextId = event.target.value;
                              setSharedBillTransactionId(nextId);
                              const nextTransaction = shareableTransactions.find(
                                (item) => String(item.id) === nextId
                              );
                              if (nextTransaction && !sharedBillTitle.trim()) {
                                setSharedBillTitle(getTransactionCategory(nextTransaction));
                              }
                              setSharedBillOwnerShare("");
                              setSharedBillParticipants((current) => current.map((person) => ({
                                ...person,
                                share_amount: "",
                              })));
                            }}
                            required
                          >
                            <option value="">Choose a debit transaction</option>
                            {shareableTransactions.map((transaction) => (
                              <option key={transaction.id} value={transaction.id}>
                                {formatDate(transaction.date)} · {getTransactionName(transaction)} · {money(getAmount(transaction))}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          <span>Bill details</span>
                          <input
                            value={sharedBillTitle}
                            onChange={(event) => setSharedBillTitle(event.target.value)}
                            maxLength={120}
                            placeholder="e.g. September rent"
                            required
                          />
                        </label>
                        <div className="shared-bill-form-heading">
                          <div>
                            <strong>Split this payment</strong>
                            <small>
                              {selectedSharedBillTransaction
                                ? `Bank payment: ${money(getAmount(selectedSharedBillTransaction))}`
                                : "Select the expense to see its bank payment."}
                            </small>
                          </div>
                          <button
                            className="text-button"
                            type="button"
                            onClick={splitSharedBillEvenly}
                            disabled={!selectedSharedBillTransaction}
                          >
                            Split equally
                          </button>
                        </div>
                        <div className="shared-bill-share-fields">
                          <label>
                            <span>Your share</span>
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              inputMode="decimal"
                              value={sharedBillOwnerShare}
                              onChange={(event) => setSharedBillOwnerShare(event.target.value)}
                              placeholder="0.00"
                              required
                            />
                          </label>
                          {sharedBillParticipants.map((participant, index) => (
                            <div className="shared-bill-person-fields" key={`person-${index}`}>
                              <label>
                                <span>Person {index + 1}</span>
                                <input
                                  value={participant.name}
                                  onChange={(event) => setSharedBillParticipants((current) =>
                                    current.map((person, personIndex) => personIndex === index
                                      ? { ...person, name: event.target.value }
                                      : person)
                                  )}
                                  maxLength={80}
                                  placeholder="Name"
                                  required
                                />
                              </label>
                              <label>
                                <span>Their share</span>
                                <input
                                  type="number"
                                  min="0.01"
                                  step="0.01"
                                  inputMode="decimal"
                                  value={participant.share_amount}
                                  onChange={(event) => setSharedBillParticipants((current) =>
                                    current.map((person, personIndex) => personIndex === index
                                      ? { ...person, share_amount: event.target.value }
                                      : person)
                                  )}
                                  placeholder="0.00"
                                  required
                                />
                              </label>
                              {sharedBillParticipants.length > 1 && (
                                <button
                                  className="shared-bill-remove-person"
                                  type="button"
                                  onClick={() => setSharedBillParticipants((current) =>
                                    current.filter((_, personIndex) => personIndex !== index)
                                  )}
                                  aria-label={`Remove person ${index + 1}`}
                                  title="Remove person"
                                >
                                  <X size={15} />
                                </button>
                              )}
                            </div>
                          ))}
                        </div>
                        <div className="shared-bill-form-footer">
                          <button
                            className="text-button"
                            type="button"
                            onClick={() => setSharedBillParticipants((current) => [
                              ...current,
                              { name: "", share_amount: "" },
                            ])}
                            disabled={sharedBillParticipants.length >= 19}
                          >
                            <Plus size={14} /> Add another person
                          </button>
                          <button
                            className="primary-button"
                            type="submit"
                            disabled={sharedBillBusy || !selectedSharedBillTransaction}
                          >
                            {sharedBillBusy ? "Saving..." : "Save shared bill"}
                          </button>
                        </div>
                        <small className="shared-bill-form-note">
                          Everyone’s shares, including yours, must add up to the full bank payment. You can split equally or enter custom amounts.
                        </small>
                      </>
                    ) : (
                      <p className="shared-bill-empty">
                        No available debit expenses in the currently selected statements. Select an expense transaction first; UPI and already-shared transactions aren’t eligible.
                      </p>
                    )}
                  </form>
                )}

                {visibleSharedBills.length > 0 ? (
                  <div className="shared-bill-list">
                    {visibleSharedBills.map((bill) => (
                      <article className="shared-bill-card" key={bill.id}>
                        <div className="shared-bill-card-heading">
                          <div>
                            <strong>{bill.title}</strong>
                            <small>{formatDate(bill.date)} · {getTransactionName(bill)}</small>
                          </div>
                          <button
                            className="shared-bill-delete"
                            type="button"
                            onClick={() => deleteSharedBill(bill)}
                            aria-label={`Remove shared bill ${bill.title}`}
                            title="Remove shared-bill tracking"
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                        <div className="shared-bill-summary">
                          <div><span>Paid from your account</span><strong>{money(bill.gross_amount)}</strong></div>
                          <div><span>Your share / counted expense</span><strong>{money(bill.owner_share)}</strong></div>
                          <div><span>Received from others</span><strong>{money(bill.repaid_amount)}</strong></div>
                          <div><span>Still owed to you</span><strong>{money(bill.amount_owed)}</strong></div>
                        </div>
                        <div className="shared-bill-participants">
                          <div className="shared-bill-participant owner-share">
                            <span><Users size={14} /> You</span>
                            <strong>{money(bill.owner_share)}</strong>
                          </div>
                          {bill.participants.map((participant) => (
                            <label className="shared-bill-participant" key={participant.id}>
                              <span>
                                <input
                                  type="checkbox"
                                  checked={Boolean(participant.is_paid)}
                                  onChange={(event) => setSharedBillRepaid(
                                    bill.id,
                                    participant.id,
                                    event.target.checked
                                  )}
                                />
                                {participant.name}
                              </span>
                              <strong>{money(participant.share_amount)}</strong>
                            </label>
                          ))}
                        </div>
                        <small className="shared-bill-footnote">
                          Mark a person as paid when their share is repaid. Repayments are not added to income.
                        </small>
                      </article>
                    ))}
                  </div>
                ) : (
                  !sharedBillFormOpen && (
                    <div className="shared-bill-empty">
                      {sharedBills.length
                        ? "Shared bills are available when their statement is selected."
                        : "No shared bills yet. Select a debit expense to split it between you and two or more people."}
                    </div>
                  )
                )}
              </section>

              <section className="content-grid">
                <article className="panel cashflow-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Statement overview</h2>
                      <p>Summary of your uploaded transactions</p>
                    </div>
                  </div>

                  {hasRealData ? (
                    <div className="statement-summary">
                      <div>
                        <span>Transactions analyzed</span>
                        <strong>{displayTransactions.length}</strong>
                      </div>
                      <div>
                        <span>Net cash flow</span>
                        <strong>{money(netCashFlow)}</strong>
                      </div>
                      <div>
                        <span>Income minus expenses</span>
                        <strong>{money(totalIncome - totalExpenses)}</strong>
                      </div>
                    </div>
                  ) : (
                    <div className="empty-state">
                      <Upload size={28} />
                      <h3>Your statement goes here</h3>
                      <p>Upload a PDF statement to calculate your income, expenses and savings.</p>
                    </div>
                  )}

                  <p className="demo-note">
                    Financial figures appear here after successful statement analysis.
                  </p>
                </article>

                <article className="panel spending-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Spending breakdown</h2>
                      <p>Categories returned by your analysis</p>
                    </div>
                    <button className="text-button" onClick={() => {
                      setSelectedCategory(null);
                      setActivePage("Analytics");
                    }}>
                      Details <ArrowUpRight size={14} />
                    </button>
                  </div>

                  <div className="spending-total">
                    <strong>{hasRealData ? money(spendingTotal) : "—"}</strong>
                    <span>Listed categories</span>
                  </div>

                  {spendingEntries.length > 0 ? (
                    <div className="spending-list">
                      {spendingEntries.map((item, index) => (
                        <div className="spending-item" key={item.label}>
                          <div className="spending-item-heading">
                            <span>
                              <i className={`category-dot category-${index % 4}`} />
                              {item.label}
                            </span>
                            <strong>{money(item.amount)}</strong>
                          </div>
                          <div className="spending-track">
                            <span
                              className={`category-fill fill-${index % 4}`}
                              style={{
                                width: `${spendingTotal > 0 ? (item.amount / spendingTotal) * 100 : 0}%`,
                              }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-state">
                      <Sparkles size={24} />
                      <p>Upload a statement to see spending categories.</p>
                    </div>
                  )}

                  <div className="insight-card">
                    <Sparkles size={18} />
                    <div>
                      <strong>A smarter money habit</strong>
                      <p>Review your spending categories to identify possible savings.</p>
                    </div>
                  </div>
                </article>
              </section>

              <section className="panel transactions-panel">
                <div className="panel-heading">
                  <div>
                    <h2>Recent transactions</h2>
                    <p>Your latest analyzed money movements</p>
                  </div>
                  <button className="text-button" onClick={() => setActivePage("Transactions")}>
                    View all <ArrowUpRight size={14} />
                  </button>
                </div>

                {recentTransactions.length > 0 ? (
                  <div className="transaction-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>TRANSACTION</th>
                          <th>CATEGORY</th>
                          <th>DATE</th>
                          <th className="amount-column">AMOUNT</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recentTransactions.map((transaction, index) => {
                          const type = getTransactionType(transaction);
                          const amountDirection = getAmountDirection(transaction);
                          return (
                            <tr key={transaction.id ?? `${getTransactionName(transaction)}-${index}`}>
                              <td>
                                <div className="transaction-name">
                                  <span className={`transaction-symbol ${type}`}>
                                    {type === "income" ? "↗" : "₹"}
                                  </span>
                                  <strong>{getTransactionName(transaction)}</strong>
                                </div>
                              </td>
                              <td>
                                <span className="category-pill">
                                  {getTransactionCategory(transaction)}
                                </span>
                              </td>
                              <td className="date-cell">
                                {formatDate(transaction.date ?? transaction.transaction_date)}
                              </td>
                              <td className={`amount-cell ${amountDirection}`}>
                                {amountDirection === "income" ? "+" : "−"}
                                {money(selectedMetric === "total_expenses"
                                  ? getCountedExpenseAmount(transaction)
                                  : getAmount(transaction))}
                                {selectedMetric === "total_expenses" &&
                                  transaction.shared_bill_owner_share != null && (
                                    <small className="gross-shared-bill-amount">
                                      Bank payment: {money(getAmount(transaction))}
                                    </small>
                                  )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="empty-state">
                    <p>No transactions loaded yet. Upload your bank statement to begin.</p>
                  </div>
                )}
              </section>
            </>
          )}

          {activePage === "Transaction Trends" && (
            <>
              <section className="analytics-heading trends-heading">
                <div>
                  <div className="eyebrow"><span className="live-dot" /> TRANSACTION TIMELINE</div>
                  <h1>Your money, <span>over time.</span></h1>
                  <p className="page-subtitle">
                    Daily income and spending across {dashboardScopeDescription}.
                  </p>
                </div>
                <button className="secondary-button" onClick={() => setActivePage("Dashboard")}>
                  <LayoutDashboard size={16} /> Back to dashboard
                </button>
              </section>

              {displayTransactions.length > 0 ? (
                <>
                  <section className="analytics-totals trends-totals">
                    <article><span>Transactions</span><strong>{displayTransactions.length}</strong></article>
                    <article><span>Total credits</span><strong className="trend-income-text">{money(timelineIncome)}</strong></article>
                    <article><span>Total debits</span><strong className="trend-expense-text">{money(timelineExpenses)}</strong></article>
                  </section>

                  <section className="panel timeline-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>Daily cash movement</h2>
                        <p>Each bar shows the total amount on that date. Hover or tap a bar for details.</p>
                      </div>
                    </div>
                    <div className="chart-legend timeline-legend">
                      <span><i className="legend-income" /> Credits</span>
                      <span><i className="legend-expense" /> Debits</span>
                    </div>
                    <div className="timeline-chart-scroll">
                      <div
                        className="timeline-chart"
                        style={{ minWidth: `${Math.max(620, transactionTimeline.length * 78)}px` }}
                      >
                        <div className="timeline-axis-labels" aria-hidden="true">
                          <span>{money(maxDailyAmount)}</span>
                          <span>{money(maxDailyAmount / 2)}</span>
                          <span>₹0</span>
                        </div>
                        <div className="timeline-plot">
                          <div className="timeline-gridline timeline-gridline-top" />
                          <div className="timeline-gridline timeline-gridline-middle" />
                          <div className="timeline-gridline timeline-gridline-bottom" />
                          <div className="timeline-columns">
                            {transactionTimeline.map((day) => (
                              <button
                                className={`timeline-day ${selectedTimelineDate === day.dateKey ? "timeline-day-selected" : ""}`}
                                key={day.dateKey}
                                onClick={() => setSelectedTimelineDate(day.dateKey)}
                                aria-label={`${formatDate(day.dateKey)}: ${day.count} transactions, credits ${money(day.income)}, debits ${money(day.expenses)}. Show day's transactions.`}
                                title={`${formatDate(day.dateKey)} · ${day.count} transactions · Credits ${money(day.income)} · Debits ${money(day.expenses)}`}
                              >
                                <div className="timeline-bars">
                                  <span
                                    className="timeline-bar timeline-income-bar"
                                    style={{ height: `${day.income > 0 && maxDailyAmount ? Math.max(2, (day.income / maxDailyAmount) * 100) : 0}%` }}
                                  />
                                  <span
                                    className="timeline-bar timeline-expense-bar"
                                    style={{ height: `${day.expenses > 0 && maxDailyAmount ? Math.max(2, (day.expenses / maxDailyAmount) * 100) : 0}%` }}
                                  />
                                </div>
                                <span className="timeline-date">{day.dateKey === "Unknown date" ? "Unknown" : formatDate(day.dateKey)}</span>
                                <span className="timeline-count">{day.count} {day.count === 1 ? "txn" : "txns"}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                    {selectedTimelineDay && (
                      <div className="timeline-detail">
                        <div className="timeline-detail-heading">
                          <div>
                            <span>DAY DETAILS</span>
                            <h3>{selectedTimelineDate === "Unknown date" ? "Undated transactions" : formatDate(selectedTimelineDate)}</h3>
                          </div>
                          <button className="text-button" onClick={() => setSelectedTimelineDate(null)}>Clear selection</button>
                        </div>
                        <div className="timeline-day-stats">
                          <div><span>Transactions</span><strong>{selectedTimelineDay.count}</strong></div>
                          <div><span>Credits</span><strong className="trend-income-text">{money(selectedTimelineDay.income)}</strong></div>
                          <div><span>Debits</span><strong className="trend-expense-text">{money(selectedTimelineDay.expenses)}</strong></div>
                          <div><span>Net movement</span><strong className={selectedTimelineDay.income - selectedTimelineDay.expenses >= 0 ? "trend-income-text" : "trend-expense-text"}>{money(selectedTimelineDay.income - selectedTimelineDay.expenses)}</strong></div>
                        </div>
                        <div className="transaction-table-wrap timeline-selected-table">
                          <table>
                            <thead><tr><th>TRANSACTION</th><th>CATEGORY</th><th>TYPE</th><th className="amount-column">AMOUNT</th></tr></thead>
                            <tbody>
                              {selectedDateTransactions.map((transaction, index) => {
                                const direction = getAmountDirection(transaction);
                                return (
                                  <tr key={transaction.id ?? `${getTransactionName(transaction)}-${index}`}>
                                    <td><strong className="category-transaction-name">{getTransactionName(transaction)}</strong></td>
                                    <td><span className="category-pill">{getTransactionCategory(transaction)}</span></td>
                                    <td className="date-cell">{direction === "income" ? "Credit" : "Debit"}</td>
                                    <td className={`amount-cell ${direction}`}>{direction === "income" ? "+" : "−"}{money(getAmount(transaction))}</td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </section>

                  <section className="panel transactions-panel full-panel timeline-transactions-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>All transactions by date</h2>
                        <p>{displayTransactions.length} transactions, newest date first.</p>
                      </div>
                    </div>
                    <div className="transaction-table-wrap">
                      <table>
                        <thead><tr><th>TRANSACTION</th><th>CATEGORY</th><th>DATE</th><th className="amount-column">AMOUNT</th></tr></thead>
                        <tbody>
                          {dateSortedTransactions.map((transaction, index) => {
                            const direction = getAmountDirection(transaction);
                            return (
                              <tr key={transaction.id ?? `${getTransactionName(transaction)}-${index}`}>
                                <td><strong className="category-transaction-name">{getTransactionName(transaction)}</strong></td>
                                <td><span className="category-pill">{getTransactionCategory(transaction)}</span></td>
                                <td className="date-cell">{formatDate(transaction.date ?? transaction.transaction_date)}</td>
                                <td className={`amount-cell ${direction}`}>{direction === "income" ? "+" : "−"}{money(getAmount(transaction))}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </section>
                </>
              ) : (
                <section className="panel empty-category-detail">
                  <Activity size={26} />
                  <p>Upload a statement to see your transaction timeline.</p>
                  <button className="primary-button" onClick={() => setActivePage("Dashboard")}>
                    <Upload size={16} /> Go to dashboard
                  </button>
                </section>
              )}
            </>
          )}

          {activePage === "Transactions" && (
            <section className="panel transactions-panel full-panel">
              <div className="panel-heading">
                <div>
                  <h2>Transactions</h2>
                  <p>
                    {filteredTransactions.length} of {displayTransactions.length} transactions shown
                    {dashboardSelectionIds.length > 1 ? ` across ${dashboardScopeDescription}` : ""}. Changing a UPI category updates matching transactions and is remembered for future payments.
                  </p>
                </div>
                <label className="upload-button">
                  <Upload size={17} /> Upload statement
                  <input type="file" accept=".pdf,application/pdf" disabled={uploading} onChange={uploadStatement} />
                </label>
              </div>

              {displayTransactions.length > 0 && (
                <div className="metric-filter-grid transaction-filter-grid" aria-label="Filter transactions">
                  <label>
                    <span>Category</span>
                    <select value={transactionFilters.category} onChange={(event) => setTransactionFilters((current) => ({ ...current, category: event.target.value }))}>
                      <option value="all">All categories</option>
                      {transactionCategoryOptions.map((category) => <option key={category} value={category}>{category}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>Type</span>
                    <select value={transactionFilters.type} onChange={(event) => setTransactionFilters((current) => ({ ...current, type: event.target.value }))}>
                      <option value="all">All types</option>
                      <option value="income">Income</option>
                      <option value="expense">Expense</option>
                      <option value="transfer">Transfer</option>
                      <option value="unknown">Unknown</option>
                    </select>
                  </label>
                  <label>
                    <span>Date from</span>
                    <input type="date" value={transactionFilters.fromDate} onChange={(event) => setTransactionFilters((current) => ({ ...current, fromDate: event.target.value }))} />
                  </label>
                  <label>
                    <span>Date to</span>
                    <input type="date" value={transactionFilters.toDate} onChange={(event) => setTransactionFilters((current) => ({ ...current, toDate: event.target.value }))} />
                  </label>
                  <label>
                    <span>Amount min (INR)</span>
                    <input type="number" min="0" step="0.01" inputMode="decimal" placeholder="Any" value={transactionFilters.minAmount} onChange={(event) => setTransactionFilters((current) => ({ ...current, minAmount: event.target.value }))} />
                  </label>
                  <label>
                    <span>Amount max (INR)</span>
                    <input type="number" min="0" step="0.01" inputMode="decimal" placeholder="Any" value={transactionFilters.maxAmount} onChange={(event) => setTransactionFilters((current) => ({ ...current, maxAmount: event.target.value }))} />
                  </label>
                  {(transactionFiltersActive || normalizedSearch) && (
                    <button className="metric-filter-reset" type="button" onClick={() => {
                      setTransactionFilters({ category: "all", type: "all", fromDate: "", toDate: "", minAmount: "", maxAmount: "" });
                      setSearchQuery("");
                    }}>Clear filters</button>
                  )}
                </div>
              )}

              {filteredTransactions.length > 0 ? (
                <div className="transaction-table-wrap">
                  <table className="main-transactions-table">
                    <thead>
                      <tr>
                        <th>CATEGORY</th>
                        <th>TRANSACTION DETAILS</th>
                        <th>TYPE</th>
                        <th>DATE</th>
                        <th className="amount-column">AMOUNT</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTransactions.map((transaction, index) => {
                        const type = getTransactionType(transaction);
                        const amountDirection = getAmountDirection(transaction);
                        return (
                          <tr key={transaction.id ?? `${getTransactionName(transaction)}-${index}`}>
                            <td>
                              <label className="category-editor">
                                <span className="sr-only">Choose category for {getTransactionName(transaction)}</span>
                                <select
                                  value={getTransactionCategory(transaction)}
                                  onChange={(event) => updateCategory(transaction, event.target.value)}
                                  aria-label={`Category for ${getTransactionName(transaction)}`}
                                >
                                  {!CATEGORY_OPTIONS.includes(getTransactionCategory(transaction)) && (
                                    <option value={getTransactionCategory(transaction)}>{getTransactionCategory(transaction)}</option>
                                  )}
                                  {CATEGORY_OPTIONS.map((category) => (
                                    <option key={category} value={category}>{category}</option>
                                  ))}
                                </select>
                              </label>
                            </td>
                            <td>
                              <div className="transaction-name">
                                <span className={`transaction-symbol ${type}`}>
                                  {type === "income" ? "↗" : "₹"}
                                </span>
                                <strong>{getTransactionName(transaction)}</strong>
                              </div>
                            </td>
                            <td className="date-cell">{getTransactionFilterType(transaction)}</td>
                            <td className="date-cell">
                              {formatDate(transaction.date ?? transaction.transaction_date)}
                            </td>
                            <td className={`amount-cell ${amountDirection}`}>
                              {amountDirection === "income" ? "+" : "−"}{money(getAmount(transaction))}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : displayTransactions.length > 0 ? (
                <div className="empty-state">
                  <p>No transactions match these filters or your search.</p>
                  <button className="text-button" onClick={() => {
                    setTransactionFilters({ category: "all", type: "all", fromDate: "", toDate: "", minAmount: "", maxAmount: "" });
                    setSearchQuery("");
                  }}>Clear filters</button>
                </div>
              ) : (
                <div className="empty-state">
                  <p>No transactions available. Upload a statement first.</p>
                </div>
              )}
            </section>
          )}

          {activePage === "Statement History" && (
            <section className="panel transactions-panel full-panel">
              <div className="panel-heading">
                <div>
                  <h2>Statement history</h2>
                  <p>Previously uploaded and analyzed statements for this account.</p>
                </div>
                <button className="text-button" onClick={() => setActivePage("Dashboard")}>
                  Back to dashboard <ArrowUpRight size={14} />
                </button>
              </div>
              {statements.length > 0 ? (
                <div className="statement-history-list">
                  {statements.map((statement) => (
                    <div className="statement-history-row" key={statement.statement_id}>
                      <button
                        className="statement-history-open"
                        onClick={() => {
                          setSelectedDashboardStatementIds([statement.statement_id]);
                          loadSavedStatement(statement.statement_id).catch((loadError) => setError(loadError.message));
                        }}
                      >
                        <span className="statement-history-icon"><History size={18} /></span>
                        <span className="statement-history-name">
                          <strong>{statement.filename || "Bank statement"}</strong>
                          <small>{formatDate(statement.created_at)} | {statement.transaction_count} transactions</small>
                        </span>
                        <ArrowUpRight size={16} />
                      </button>
                      <select
                        className="statement-bank-assignment"
                        aria-label={`Bank account for ${statement.filename || "statement"}`}
                        value={statement.bank_account_id ?? ""}
                        onChange={(event) => assignStatementToBankAccount(statement.statement_id, event.target.value)}
                      >
                        <option value="">Unassigned</option>
                        {bankAccounts.map((bankAccount) => (
                          <option key={bankAccount.id} value={bankAccount.id}>{bankAccount.name}</option>
                        ))}
                      </select>
                      {statement.pdf_available && (
                        <a
                          className="statement-history-download"
                          href={`${API}/statements/${statement.statement_id}/pdf`}
                          download
                          aria-label={`Download ${statement.filename || "bank statement"}`}
                          title="Download original PDF"
                        >
                          <Download size={16} />
                          <span>PDF</span>
                        </a>
                      )}
                      <button
                        className="statement-history-delete"
                        type="button"
                        onClick={() => deleteStatement(statement)}
                        aria-label={`Delete ${statement.filename || "bank statement"}`}
                        title="Delete statement and its transactions"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-state">
                  <History size={26} />
                  <p>No statements have been uploaded to this account yet.</p>
                </div>
              )}
            </section>
          )}

          {activePage === "Analytics" && (
            selectedMetric ? (
              <>
                <section className="analytics-heading">
                  <div>
                    <div className="eyebrow"><span className="live-dot" /> CALCULATION DETAILS</div>
                    <h1>{metricDetail.title}</h1>
                    <p className="page-subtitle">See how this figure is calculated and which transactions contribute.</p>
                  </div>
                  <div className="analytics-heading-actions">
                    <button className="secondary-button" onClick={() => {
                      setSelectedMetric(null);
                      setActivePage("Dashboard");
                    }}>
                      <LayoutDashboard size={16} /> Back to dashboard
                    </button>
                    <button className="secondary-button" onClick={() => setSelectedMetric(null)}>
                      <ChartNoAxesCombined size={16} /> All categories
                    </button>
                  </div>
                </section>

                <section className="panel metric-calculation">
                  <span>Calculation</span>
                  <strong>{metricDetail.value}</strong>
                  <p>{metricDetail.formula}</p>
                  <small>{metricDetail.explanation}</small>
                </section>

                {selectedMetric === "total_income" && upiReceivedTransactions.length > 0 && (
                  <section className="panel income-choice-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>Choose UPI credits to count as income</h2>
                        <p>Selected choices are saved to your account and included in income totals.</p>
                      </div>
                    </div>
                    <div className="transaction-table-wrap">
                      <table className="metric-transactions-table">
                        <thead>
                          <tr>
                            <th>INCLUDE IN INCOME</th>
                            <th>TRANSACTION</th>
                            <th>DATE</th>
                            <th className="amount-column">AMOUNT</th>
                          </tr>
                        </thead>
                        <tbody>
                          {upiReceivedTransactions.map((transaction, index) => (
                            <tr key={transaction.id ?? `${transaction.description}-${index}`}>
                              <td>
                                <label className="income-inclusion-choice">
                                  <input
                                    type="checkbox"
                                    checked={Boolean(transaction.income_included)}
                                    disabled={incomeInclusionBusyId === transaction.id}
                                    onChange={(event) => toggleIncomeInclusion(
                                      transaction,
                                      event.target.checked
                                    )}
                                  />
                                  <span>
                                    {transaction.income_included
                                      ? "Count as income"
                                      : "Separate UPI activity"}
                                  </span>
                                </label>
                              </td>
                              <td><strong className="category-transaction-name">{getTransactionName(transaction)}</strong></td>
                              <td className="date-cell">{formatDate(transaction.date)}</td>
                              <td className="amount-cell income">{money(getAmount(transaction))}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                )}

                <section className="panel transactions-panel metric-transactions-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Transactions included</h2>
                      <p>{metricFiltersActive
                        ? `${filteredMetricTransactions.length} of ${selectedMetricTransactions.length} transactions match these filters`
                        : `${selectedMetricTransactions.length} transactions used in this calculation`}</p>
                    </div>
                  </div>
                  {selectedMetricTransactions.length > 0 && (
                    <div className="metric-filter-grid" aria-label="Filter included transactions">
                      <label>
                        <span>Category</span>
                        <select
                          value={metricFilters.category}
                          onChange={(event) => setMetricFilters((current) => ({ ...current, category: event.target.value }))}
                        >
                          <option value="all">All categories</option>
                          {metricCategoryOptions.map((category) => (
                            <option key={category} value={category}>{category}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span>Type</span>
                        <select
                          value={metricFilters.type}
                          onChange={(event) => setMetricFilters((current) => ({ ...current, type: event.target.value }))}
                        >
                          <option value="all">All types</option>
                          <option value="income">Income</option>
                          <option value="expense">Expense</option>
                        </select>
                      </label>
                      <label>
                        <span>Date from</span>
                        <input
                          type="date"
                          value={metricFilters.fromDate}
                          onChange={(event) => setMetricFilters((current) => ({ ...current, fromDate: event.target.value }))}
                        />
                      </label>
                      <label>
                        <span>Date to</span>
                        <input
                          type="date"
                          value={metricFilters.toDate}
                          onChange={(event) => setMetricFilters((current) => ({ ...current, toDate: event.target.value }))}
                        />
                      </label>
                      <label>
                        <span>Amount min (₹)</span>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          inputMode="decimal"
                          placeholder="Any"
                          value={metricFilters.minAmount}
                          onChange={(event) => setMetricFilters((current) => ({ ...current, minAmount: event.target.value }))}
                        />
                      </label>
                      <label>
                        <span>Amount max (₹)</span>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          inputMode="decimal"
                          placeholder="Any"
                          value={metricFilters.maxAmount}
                          onChange={(event) => setMetricFilters((current) => ({ ...current, maxAmount: event.target.value }))}
                        />
                      </label>
                      {metricFiltersActive && (
                        <button
                          className="metric-filter-reset"
                          type="button"
                          onClick={() => setMetricFilters({ category: "all", type: "all", fromDate: "", toDate: "", minAmount: "", maxAmount: "" })}
                        >
                          Clear filters
                        </button>
                      )}
                    </div>
                  )}
                  {filteredMetricTransactions.length > 0 ? (
                    <div className="transaction-table-wrap">
                      <table className="metric-transactions-table">
                        <thead><tr><th>CATEGORY</th><th>TRANSACTION DETAILS</th><th>TYPE</th><th>DATE</th><th className="amount-column">AMOUNT</th></tr></thead>
                        <tbody>
                          {filteredMetricTransactions.map((transaction, index) => {
                            const amountDirection = getAmountDirection(transaction);
                            return (
                              <tr key={transaction.id ?? `${transaction.description}-${index}`}>
                                <td><span className="category-pill">{getAnalyticsCategory(transaction)}</span></td>
                                <td><strong className="category-transaction-name">{getTransactionName(transaction)}</strong></td>
                                <td className="date-cell">
                                  {transaction.income_included
                                    ? "income (selected)"
                                    : transaction.transaction_type}
                                </td>
                                <td className="date-cell">{formatDate(transaction.date)}</td>
                                <td className={`amount-cell ${amountDirection}`}>
                                  {amountDirection === "income" ? "+" : "−"}{money(getAmount(transaction))}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="empty-category-detail"><p>{selectedMetricTransactions.length > 0 ? "No transactions match these filters." : "No transactions contribute to this calculation yet."}</p></div>
                  )}
                </section>
              </>
            ) : (
            <>
              <section className="analytics-heading">
                <div>
                  <div className="eyebrow"><span className="live-dot" /> SPENDING DETAILS</div>
                  <h1>Explore your <span>categories.</span></h1>
                  <p className="page-subtitle">Choose a category to inspect its transactions, including Other and UPI Sent/Received.</p>
                </div>
                <button className="secondary-button" onClick={() => setActivePage("Dashboard")}>
                  <LayoutDashboard size={16} /> Back to dashboard
                </button>
              </section>

              {hasRealData ? (
                <>
                  <div className="analytics-totals">
                    <article><span>Total income</span><strong>{money(totalIncome)}</strong></article>
                    <article><span>Total expenses</span><strong>{money(totalExpenses)}</strong></article>
                    <article><span>Net cash flow</span><strong>{money(netCashFlow)}</strong></article>
                  </div>
                  <div className="analytics-totals upi-analytics-totals">
                    <article><span>UPI received (separate)</span><strong>{money(totalUpiReceived)}</strong></article>
                    <article><span>UPI sent (separate)</span><strong>{money(totalUpiSent)}</strong></article>
                  </div>

                  {allCategoryEntries.length > 0 ? (
                    <section className="category-detail-layout category-detail-layout-popup">
                      <div className="category-cards">
                        {allCategoryEntries.map((item, index) => (
                          <button
                            className={`category-summary-card ${selectedCategory === item.label ? "selected" : ""}`}
                            key={item.label}
                            onClick={() => setSelectedCategory(item.label)}
                          >
                            <span className="category-summary-top">
                              <i className={`category-dot category-${index % 4}`} />
                              <span>{item.label}</span>
                              <ArrowUpRight size={15} />
                            </span>
                            <strong>{money(item.amount)}</strong>
                            <span className="category-count">
                              {item.count} transactions
                            </span>
                            <span className="spending-track">
                              <span
                                className={`category-fill fill-${index % 4}`}
                                style={{ width: `${allCategoryTotal > 0 ? (item.amount / allCategoryTotal) * 100 : 0}%` }}
                              />
                            </span>
                          </button>
                        ))}
                      </div>

                      {selectedCategory && (
                        <button
                          className="category-popup-backdrop"
                          type="button"
                          aria-label="Close category transactions"
                          onClick={() => setSelectedCategory(null)}
                        />
                      )}
                      <section
                        className={`panel category-transactions-panel ${selectedCategory ? "category-popup-open" : "category-popup-closed"}`}
                        role={selectedCategory ? "dialog" : undefined}
                        aria-modal={selectedCategory ? "true" : undefined}
                        aria-label={selectedCategory ? `${selectedCategory} transactions` : undefined}
                      >
                        {selectedCategory ? (
                          <>
                            <div className="panel-heading">
                              <div>
                                <h2>{selectedCategory}</h2>
                                <p>{selectedCategoryTransactions.length} transactions | {money(allCategoryEntries.find((item) => item.label === selectedCategory)?.amount)}</p>
                              </div>
                              <button className="text-button category-popup-close" onClick={() => setSelectedCategory(null)} aria-label="Close category transactions">
                                <X size={18} /> Close
                              </button>
                            </div>
                            {selectedCategoryTransactions.length > 0 ? (
                              <div className="transaction-table-wrap">
                                <table>
                                  <thead><tr><th>TRANSACTION</th><th>DATE</th><th className="amount-column">AMOUNT</th></tr></thead>
                                  <tbody>
                                    {selectedCategoryTransactions.map((transaction, index) => (
                                      <tr key={transaction.id ?? `${transaction.description}-${index}`}>
                                        <td><strong className="category-transaction-name">{getTransactionName(transaction)}</strong></td>
                                        <td className="date-cell">{formatDate(transaction.date)}</td>
                                        <td className={`amount-cell ${getAmountDirection(transaction)}`}>
                                          {getAmountDirection(transaction) === "income" ? "+" : "−"}{money(getAmount(transaction))}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            ) : (
                              <p className="empty-category-detail">No transactions were found in this category.</p>
                            )}
                          </>
                        ) : (
                          <div className="empty-category-detail">
                            <ChartNoAxesCombined size={24} />
                            <p>Select a category to inspect its transactions.</p>
                          </div>
                        )}
                      </section>
                    </section>
                  ) : (
                    <div className="panel empty-category-detail"><p>No spending categories are available yet.</p></div>
                  )}
                </>
              ) : (
                <section className="panel empty-category-detail">
                  <p>Upload a statement to explore your spending categories.</p>
                  <button className="primary-button" onClick={() => setActivePage("Dashboard")}>
                    <Upload size={16} /> Go to dashboard
                  </button>
                </section>
              )}
            </>
            )
          )}

          {activePage === "AI Assistant" && (
            <section className="panel chat-panel">
              <div className="chat-welcome">
                <span className="chat-logo"><Sparkles size={24} /></span>
                <h2>Meet your money assistant.</h2>
                <p>Choose statements for questions about your finances. General questions do not use statement data.</p>
              </div>

              {statements.length > 0 && (
                <div className="ai-statement-picker">
                  <strong>Analyze these statements</strong>
                  <label className="ai-select-all">
                    <input
                      type="checkbox"
                      checked={aiStatementIds.length === statements.length}
                      onChange={(event) => {
                        setAiStatementIds(event.target.checked
                          ? statements.map((statement) => statement.statement_id)
                          : []);
                        setMessages([]);
                        setError("");
                      }}
                    />
                    <span>Select all statements</span>
                  </label>
                  {statementGroups.map((group) => group.statements.length > 0 && (
                    <section className="ai-statement-group" key={group.id}>
                      <strong>{group.name}</strong>
                      <div className="ai-statement-options">
                        {group.statements.map((statement) => (
                          <label key={statement.statement_id}>
                            <input
                              type="checkbox"
                              checked={aiStatementIds.includes(statement.statement_id)}
                              onChange={(event) => {
                                setAiStatementIds((current) => event.target.checked
                                  ? [...current, statement.statement_id]
                                  : current.filter((id) => id !== statement.statement_id));
                                setMessages([]);
                                setError("");
                              }}
                            />
                            <span>
                              <strong>{statement.filename || "Bank statement"}</strong>
                              <small>{formatDate(statement.created_at)} · {statement.transaction_count} transactions</small>
                            </span>
                          </label>
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              )}

              <div className="suggestion-grid">
                {[
                  "Where am I spending the most?",
                  "How can I save more?",
                  "Summarize my monthly expenses",
                ].map((prompt) => (
                  <button key={prompt} onClick={() => setQuestion(prompt)}>
                    {prompt} <ArrowUpRight size={15} />
                  </button>
                ))}
              </div>

              <div className="chat-messages">
                {messages.map((message, index) => (
                  <div
                    className={message.role === "user" ? "chat-user-message" : "chat-assistant-message"}
                    key={index}
                  >
                    {message.text}
                    {message.suggestions?.length > 0 && (
                      <div className="saving-suggestions">
                        <span className="saving-suggestions-title">Ideas based on your spending</span>
                        {message.suggestions.map((suggestion) => (
                          <article className="saving-suggestion-card" key={suggestion.category}>
                            <div className="saving-suggestion-heading">
                              <strong>{suggestion.category}</strong>
                              <span>{money(suggestion.amount)}</span>
                            </div>
                            <small>{suggestion.share}% of your categorized expenses</small>
                            <p>{suggestion.tip}</p>
                          </article>
                        ))}
                      </div>
                    )}
                    {message.transactions?.length > 0 && (
                      <div className="category-results">
                        {message.transactions.map((transaction, transactionIndex) => {
                          const transactionType = getAmountDirection(transaction);
                          return (
                            <article
                              className="category-result-row"
                              key={transaction.id ?? `${transaction.description}-${transactionIndex}`}
                            >
                              <div className="category-result-details">
                                <strong>{getTransactionName(transaction)}</strong>
                                <span>{formatDate(transaction.date)}</span>
                              </div>
                              <strong className={`category-result-amount ${transactionType}`}>
                                {transactionType === "income" ? "+" : "−"}
                                {money(getAmount(transaction))}
                              </strong>
                            </article>
                          );
                        })}
                      </div>
                    )}
                    {message.followUps?.length > 0 && (
                      <div className="follow-up-questions" aria-label="Suggested follow-up questions">
                        <span>Ask next</span>
                        {message.followUps.map((prompt) => (
                          <button
                            key={prompt}
                            type="button"
                            disabled={asking}
                            onClick={() => askQuestion(prompt)}
                          >
                            {prompt} <ArrowUpRight size={13} />
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                {asking && <div className="chat-assistant-message">Stack Up is thinking...</div>}
              </div>

              <form className="chat-input-form" onSubmit={sendQuestion}>
                <input
                  ref={chatInputRef}
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="Ask anything about your money..."
                  disabled={asking}
                />
                <button type="submit" aria-label="Send question" disabled={asking}>
                  <ArrowUpRight size={19} />
                </button>
              </form>

              <p className="demo-note">
                For AI answers, up to 12 recent chat turns may be sent to Groq. Chat history is not saved in Stack Up.
              </p>
            </section>
          )}

          <footer className="footer">
            <span>STACK UP <span className="footer-dot">●</span> YOUR FINANCES, MADE CLEAR.</span>
            <span><CircleHelp size={14} /> Built for better money decisions</span>
          </footer>
        </div>
      </main>
    </div>
  );
}

export default App;
