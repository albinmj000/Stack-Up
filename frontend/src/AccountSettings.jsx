import { useCallback, useEffect, useState } from "react";
import { Download, KeyRound, Monitor, Moon, Sun, Trash2, UserRound, ShieldCheck } from "lucide-react";
import { API, readApiResponse } from "./api";

async function sendJson(path, method, body) {
  const response = await fetch(`${API}${path}`, {
    method,
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await readApiResponse(response);
  if (!response.ok) throw new Error(data.detail || "The request could not be completed.");
  return data;
}

async function fetchSettings() {
  const response = await fetch(`${API}/auth/settings`, { credentials: "include" });
  const data = await readApiResponse(response);
  if (!response.ok) throw new Error(data.detail || "Could not load account settings.");
  return data;
}

function SettingsCard({ icon: Icon, title, description, children, className = "" }) {
  return (
    <section className={`settings-card ${className}`}>
      <div className="settings-card-heading">
        <span className="settings-icon"><Icon size={18} /></span>
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

export default function AccountSettings({ account, theme, setTheme, onProfileUpdated, onDeleted }) {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [username, setUsername] = useState(account?.username || "");
  const [profilePassword, setProfilePassword] = useState("");
  const [passwordFields, setPasswordFields] = useState({ current: "", next: "", code: "" });
  const [contactDrafts, setContactDrafts] = useState({ email: "", phone: "" });
  const [contactCodes, setContactCodes] = useState({ email: "", phone: "" });
  const [deleteFields, setDeleteFields] = useState({ password: "", code: "", confirmation: "" });

  const loadSettings = useCallback(async () => {
    try {
      const data = await fetchSettings();
      setError("");
      setSettings(data);
      setUsername(data.account.username || "");
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    fetchSettings()
      .then((data) => {
        if (!mounted) return;
        setSettings(data);
        setUsername(data.account.username || "");
      })
      .catch((loadError) => {
        if (mounted) setError(loadError.message);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  async function runAction(key, action, successMessage) {
    setBusy(key);
    setError("");
    setNotice("");
    try {
      const result = await action();
      if (successMessage) setNotice(successMessage);
      return result;
    } catch (actionError) {
      setError(actionError.message);
      return null;
    } finally {
      setBusy("");
    }
  }

  async function saveUsername(event) {
    event.preventDefault();
    const result = await runAction(
      "profile",
      () => sendJson("/auth/settings/profile", "PUT", {
        username,
        current_password: profilePassword,
      }),
      "Username updated.",
    );
    if (result) {
      setProfilePassword("");
      onProfileUpdated({ ...account, username: result.username });
      await loadSettings();
    }
  }

  async function requestContactCode(channel) {
    const contact = contactDrafts[channel].trim();
    if (!contact) {
      setError(`Enter the new ${channel} first.`);
      return;
    }
    const result = await runAction(
      `contact-${channel}`,
      () => sendJson("/auth/settings/contact/request", "POST", { contact }),
      "Verification code sent.",
    );
    if (result) setContactCodes((current) => ({ ...current, [channel]: "" }));
  }

  async function verifyContact(channel) {
    const contact = contactDrafts[channel].trim();
    const result = await runAction(
      `verify-${channel}`,
      () => sendJson("/auth/settings/contact/verify", "POST", {
        contact,
        code: contactCodes[channel],
      }),
      `${channel === "email" ? "Email" : "Phone"} updated.`,
    );
    if (result) {
      onProfileUpdated({ ...account, email: result.email, phone: result.phone });
      setContactDrafts((current) => ({ ...current, [channel]: "" }));
      setContactCodes((current) => ({ ...current, [channel]: "" }));
      await loadSettings();
    }
  }

  async function changePassword(event) {
    event.preventDefault();
    const result = await runAction(
      "password",
      () => sendJson("/auth/settings/password", "PUT", {
        current_password: passwordFields.current,
        new_password: passwordFields.next,
        verification_code: passwordFields.code,
      }),
      "Password updated. Other active sign-in sessions were signed out.",
    );
    if (result) {
      setPasswordFields({ current: "", next: "", code: "" });
      await loadSettings();
    }
  }

  async function sendAccountCode(purpose) {
    return runAction(
      `code-${purpose}`,
      () => sendJson("/auth/settings/verification-code", "POST", { purpose }),
      "Verification code sent.",
    );
  }

  async function removeRemembered(userId) {
    const result = await runAction(
      `remove-${userId}`,
      () => sendJson("/auth/settings/remembered-accounts/remove", "POST", { user_id: userId }),
      "Remembered account removed from this device.",
    );
    if (result) await loadSettings();
  }

  async function exportAccountData() {
    setBusy("export");
    setError("");
    setNotice("");
    try {
      const response = await fetch(`${API}/auth/settings/export`, { credentials: "include" });
      if (!response.ok) {
        const data = await readApiResponse(response);
        throw new Error(data.detail || "Account data could not be exported.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "stack-up-account-export.json";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("Your account export has been downloaded.");
    } catch (exportError) {
      setError(exportError.message);
    } finally {
      setBusy("");
    }
  }

  async function deleteAccount(event) {
    event.preventDefault();
    const result = await runAction(
      "delete",
      () => sendJson("/auth/settings/delete-account", "POST", deleteFields),
    );
    if (result) onDeleted();
  }

  function selectTheme(value) {
    setTheme(value);
    try {
      window.localStorage.setItem(`stackup:theme:${account?.user_id || "account"}`, value);
    } catch {
      setError("Appearance preference could not be saved in this browser.");
    }
  }

  return (
    <div className="account-settings-page">
      <div className="settings-page-heading">
        <div className="eyebrow"><span className="live-dot" /> PERSONAL ACCOUNT</div>
        <h1>Account <span>settings.</span></h1>
        <p className="page-subtitle">Manage your profile, sign-in security, data, and appearance.</p>
      </div>

      {notice && <div className="notice-message" role="status">{notice}</div>}
      {error && <div className="error-message" role="alert">{error}</div>}
      {loading ? <p className="settings-loading">Loading account settings…</p> : (
        <div className="settings-grid">
          <SettingsCard icon={UserRound} title="Profile" description="Update your username and verified sign-in contacts.">
            <form className="settings-form" onSubmit={saveUsername}>
              <label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} minLength={3} maxLength={24} required /></label>
              {settings?.has_password && (
                <label>Current password<input type="password" autoComplete="current-password" value={profilePassword} onChange={(event) => setProfilePassword(event.target.value)} required /></label>
              )}
              <button className="secondary-button" type="submit" disabled={Boolean(busy)}>Save username</button>
            </form>
            {["email", "phone"].map((channel) => (
              <div className="settings-contact-row" key={channel}>
                <div className="settings-contact-current">
                  <strong>{channel === "email" ? "Email" : "Phone"}</strong>
                  <span>{settings?.account?.[channel] || "Not added"}</span>
                </div>
                <label className="settings-contact-input">
                  New {channel}
                  <input
                    type={channel === "email" ? "email" : "tel"}
                    value={contactDrafts[channel]}
                    onChange={(event) => setContactDrafts((current) => ({ ...current, [channel]: event.target.value }))}
                    placeholder={channel === "email" ? "name@example.com" : "+91 98765 43210"}
                  />
                </label>
                <button className="secondary-button" type="button" disabled={Boolean(busy)} onClick={() => requestContactCode(channel)}>
                  Send code
                </button>
                {contactDrafts[channel] && (
                  <div className="settings-verify-row">
                    <input aria-label={`${channel} verification code`} inputMode="numeric" value={contactCodes[channel]} onChange={(event) => setContactCodes((current) => ({ ...current, [channel]: event.target.value.replace(/\D/g, "").slice(0, 6) }))} placeholder="6-digit code" />
                    <button className="primary-button" type="button" disabled={Boolean(busy) || contactCodes[channel].length !== 6} onClick={() => verifyContact(channel)}>Verify contact</button>
                  </div>
                )}
              </div>
            ))}
          </SettingsCard>

          <SettingsCard icon={KeyRound} title="Password" description="Use a unique password of at least 8 characters.">
            <form className="settings-form" onSubmit={changePassword}>
              {settings?.has_password ? (
                <label>Current password<input type="password" autoComplete="current-password" value={passwordFields.current} onChange={(event) => setPasswordFields((current) => ({ ...current, current: event.target.value }))} required /></label>
              ) : (
                <div className="settings-verify-row">
                  <button className="secondary-button" type="button" disabled={Boolean(busy)} onClick={() => sendAccountCode("password_change")}>Send verification code</button>
                  <input aria-label="Password verification code" inputMode="numeric" value={passwordFields.code} onChange={(event) => setPasswordFields((current) => ({ ...current, code: event.target.value.replace(/\D/g, "").slice(0, 6) }))} placeholder="6-digit code" required />
                </div>
              )}
              <label>New password<input type="password" autoComplete="new-password" minLength={8} maxLength={128} value={passwordFields.next} onChange={(event) => setPasswordFields((current) => ({ ...current, next: event.target.value }))} required /></label>
              <button className="secondary-button" type="submit" disabled={Boolean(busy)}>{settings?.has_password ? "Change password" : "Set password"}</button>
            </form>
          </SettingsCard>

          <SettingsCard icon={ShieldCheck} title="Remembered accounts" description="These accounts can be switched on this device only. This is not a list of all signed-in devices.">
            <div className="settings-remembered-list">
              {(settings?.remembered_accounts || []).map((savedAccount) => (
                <div className="settings-remembered-item" key={savedAccount.user_id}>
                  <span>{savedAccount.username || savedAccount.email || savedAccount.phone || "Personal account"}</span>
                  {savedAccount.active ? <small>Current account</small> : (
                    <button className="text-button" type="button" disabled={Boolean(busy)} onClick={() => removeRemembered(savedAccount.user_id)}>Remove</button>
                  )}
                </div>
              ))}
              {!settings?.remembered_accounts?.length && <p>No remembered accounts were found on this device.</p>}
            </div>
          </SettingsCard>

          <SettingsCard icon={Download} title="Your data" description="Download your account details, statements, transactions, and category corrections.">
            <p className="settings-note">Original statement PDFs are included in the JSON export as Base64-encoded data.</p>
            <button className="secondary-button" type="button" onClick={exportAccountData} disabled={Boolean(busy)}>
              <Download size={15} /> {busy === "export" ? "Preparing export…" : "Download my data"}
            </button>
          </SettingsCard>

          <SettingsCard icon={Monitor} title="Appearance" description="Choose the look of Stack Up in this browser and account.">
            <div className="settings-theme-options">
              <button className={`theme-choice ${theme === "dark" ? "selected" : ""}`} type="button" onClick={() => selectTheme("dark")} aria-pressed={theme === "dark"}><Moon size={17} /> Dark</button>
              <button className={`theme-choice ${theme === "light" ? "selected" : ""}`} type="button" onClick={() => selectTheme("light")} aria-pressed={theme === "light"}><Sun size={17} /> Light</button>
            </div>
          </SettingsCard>

          <SettingsCard icon={Trash2} title="Delete account and data" description="Permanently remove your account, uploaded statements, transactions, and saved category corrections." className="settings-danger-card">
            <p className="settings-danger-warning">This cannot be undone. You must reauthenticate and enter DELETE MY ACCOUNT below.</p>
            {!settings?.has_password && (
              <button className="secondary-button" type="button" disabled={Boolean(busy)} onClick={() => sendAccountCode("account_deletion")}>Send deletion verification code</button>
            )}
            <form className="settings-form" onSubmit={deleteAccount}>
              {settings?.has_password ? (
                <label>Password<input type="password" autoComplete="current-password" value={deleteFields.password} onChange={(event) => setDeleteFields((current) => ({ ...current, password: event.target.value }))} required /></label>
              ) : (
                <label>Verification code<input inputMode="numeric" value={deleteFields.code} onChange={(event) => setDeleteFields((current) => ({ ...current, code: event.target.value.replace(/\D/g, "").slice(0, 6) }))} required /></label>
              )}
              <label>Confirmation phrase<input value={deleteFields.confirmation} onChange={(event) => setDeleteFields((current) => ({ ...current, confirmation: event.target.value }))} placeholder="DELETE MY ACCOUNT" required /></label>
              <button className="danger-button" type="submit" disabled={Boolean(busy) || deleteFields.confirmation !== "DELETE MY ACCOUNT"}>{busy === "delete" ? "Deleting…" : "Permanently delete account"}</button>
            </form>
          </SettingsCard>
        </div>
      )}
    </div>
  );
}
