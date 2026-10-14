const configuredApiBase = import.meta.env.VITE_API_BASE_URL?.trim();

export const API = (configuredApiBase || "/api").replace(/\/+$/, "");

const SESSION_KEY = "stack_up_native_session";
const DEVICE_KEY = "stack_up_native_device";

function isNativeApp() {
  return Boolean(globalThis.Capacitor?.isNativePlatform?.());
}

// The native WebView runs on another origin than the API, so cookies are not
// reliably sent. The native app stores the issued tokens and sends them as headers.
if (isNativeApp() && !globalThis.__stackUpFetchPatched) {
  globalThis.__stackUpFetchPatched = true;
  const nativeFetch = globalThis.fetch.bind(globalThis);

  globalThis.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input?.url || "";
    if (!url.startsWith(API)) return nativeFetch(input, init);

    const headers = new Headers(init.headers || {});
    headers.set("X-Stack-Up-Client", "native");
    const session = localStorage.getItem(SESSION_KEY);
    const device = localStorage.getItem(DEVICE_KEY);
    if (session) headers.set("X-Stack-Up-Session-Token", session);
    if (device) headers.set("X-Stack-Up-Device-Token", device);

    const response = await nativeFetch(input, { ...init, headers });

    const newSession = response.headers.get("X-Stack-Up-Session-Token");
    const newDevice = response.headers.get("X-Stack-Up-Device-Token");
    if (newSession) localStorage.setItem(SESSION_KEY, newSession);
    if (newDevice) localStorage.setItem(DEVICE_KEY, newDevice);
    if (url.startsWith(`${API}/auth/logout`)) {
      localStorage.removeItem(SESSION_KEY);
      localStorage.removeItem(DEVICE_KEY);
    }
    if (url.startsWith(`${API}/auth/add-account`)) {
      localStorage.removeItem(SESSION_KEY);
    }
    return response;
  };
}

export async function readApiResponse(response) {
  const body = await response.text();
  const status = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;

  if (!body.trim()) {
    if (!response.ok) {
      throw new Error(`The API returned an empty response (${status}). Check the backend deployment logs.`);
    }
    return {};
  }

  try {
    return JSON.parse(body);
  } catch {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("text/html") || /^\s*<!doctype html/i.test(body)) {
      throw new Error(
        `The request returned a web page instead of the Stack Up API (${status}). ` +
        "Check VITE_API_BASE_URL in the frontend deployment settings."
      );
    }
    throw new Error(`The API returned an invalid response (${status}). Check the backend deployment logs.`);
  }
}
