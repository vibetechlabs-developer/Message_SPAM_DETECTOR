// In dev, use same-origin `/api` so Vite proxies to SalesBooster (`server.urls`). Calling
// `http://127.0.0.1:8000` directly often hits a different project (e.g. `backend.urls`).
const allowAbsoluteInDev =
  import.meta.env.VITE_ALLOW_ABSOLUTE_API_IN_DEV === "true";
const API_BASE_URL =
  import.meta.env.DEV && !allowAbsoluteInDev
    ? ""
    : import.meta.env.VITE_API_BASE_URL || "";

export const apiUrl = (path) => `${API_BASE_URL}${path}`;
