const configuredApiBase = import.meta.env.VITE_API_BASE_URL?.trim();

export const API = (configuredApiBase || "/api").replace(/\/+$/, "");

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
