/**
 * The single place in the app that talks HTTP. Every call sends
 * `credentials: "include"` because the session is an httpOnly cookie
 * (`sw_session`); in dev the paths are proxied to the API so they stay
 * same-origin (see vite.config.ts). No component may call `fetch` directly.
 */
import type {
  ExportFormat,
  LoginBody,
  MappingOverride,
  ResultOut,
  SchemaOut,
  SchemaTemplateMap,
  SchemaWrite,
  SessionOut,
  SignupBody,
  UploadOut,
  UploadStatus,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  /** Parsed response body, when the server sent JSON. Used for 409/422. */
  readonly payload: unknown;

  constructor(status: number, message: string, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

/** Thrown when the network itself fails (API down, offline, proxy refused). */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("Could not reach the Sheetwright API.");
    this.name = "NetworkError";
    this.cause = cause;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * Error bodies are not part of the frozen contract, so read them defensively:
 * FastAPI wraps handler payloads in `detail`, but plain bodies are also
 * accepted. Both shapes are unwrapped to a single record.
 */
function errorBody(payload: unknown): Record<string, unknown> {
  if (!isRecord(payload)) return {};
  const detail = payload.detail;
  if (isRecord(detail)) return detail;
  return payload;
}

/**
 * FastAPI's request-validation 422 is a list of `{loc, msg}` entries, not a
 * sentence. Without this a schema the server rejects would surface as the
 * useless "Request failed (HTTP 422)".
 */
function validationMessage(payload: unknown): string | null {
  if (!isRecord(payload) || !Array.isArray(payload.detail)) return null;
  const messages = payload.detail
    .map((item) => (isRecord(item) && typeof item.msg === "string" ? item.msg : null))
    .filter((message): message is string => Boolean(message));
  return messages.length ? messages.join("; ") : null;
}

function errorMessage(status: number, payload: unknown): string {
  const body = errorBody(payload);
  for (const key of ["message", "error", "detail"]) {
    const value = body[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  const validation = validationMessage(payload);
  if (validation) return validation;
  // A 5xx with no JSON body is almost always the API being down or the dev
  // proxy failing to connect, so name that rather than showing a bare code.
  if (status >= 500) {
    return `The Sheetwright API is not responding (HTTP ${status}).`;
  }
  return `Request failed (HTTP ${status}).`;
}

/**
 * All API routes are namespaced under /api so they cannot collide with the
 * app's own client-side routes (the SPA has its own /uploads page).
 */
const API_BASE = "/api";

/** Live status carried by a 409 from `/result` ("valid request, wrong time"). */
export function conflictStatus(error: unknown): UploadStatus | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const status = errorBody(error.payload).status;
  return typeof status === "string" ? (status as UploadStatus) : null;
}

/** `error` + `required_action` carried by a 422 from `/result`. */
export function failureDetail(
  error: unknown,
): { error: string | null; required_action: string | null } | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null;
  const body = errorBody(error.payload);
  const read = (key: string) =>
    typeof body[key] === "string" ? (body[key] as string) : null;
  return { error: read("error"), required_action: read("required_action") };
}

/**
 * A 409 from `/schemas` can only mean "that name is taken" (it is the one
 * uniqueness constraint in the contract), so the editor can attach the message
 * to the name input instead of showing a generic banner.
 */
export function isDuplicateName(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { credentials: "include", ...init });
  } catch (cause) {
    throw new NetworkError(cause);
  }
  if (!response.ok) {
    const payload = await response
      .clone()
      .json()
      .catch(() => null);
    throw new ApiError(response.status, errorMessage(response.status, payload), payload);
  }
  return response;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await request(path);
  return (await response.json()) as T;
}

async function sendJson<T>(
  path: string,
  method: "POST" | "PUT",
  body?: unknown,
): Promise<T> {
  const response = await request(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return (await response.json()) as T;
}

/* ---------------------------------------------------------------- Session */

export const auth = {
  me: () => getJson<SessionOut>("/auth/me"),
  trial: () => sendJson<SessionOut>("/auth/trial", "POST"),
  signup: (body: SignupBody) => sendJson<SessionOut>("/auth/signup", "POST", body),
  login: (body: LoginBody) => sendJson<SessionOut>("/auth/login", "POST", body),
  logout: async () => {
    await request("/auth/logout", { method: "POST" });
  },
};

/* ---------------------------------------------------------------- Schemas */

export const schemas = {
  list: () => getJson<SchemaOut[]>("/schemas"),
  templates: () => getJson<SchemaTemplateMap>("/schemas/templates"),
  get: (id: string) => getJson<SchemaOut>(`/schemas/${encodeURIComponent(id)}`),

  create: (body: SchemaWrite) => sendJson<SchemaOut>("/schemas", "POST", body),

  /** Copies a named template into the org; the server picks the new id. */
  createFromTemplate: (key: string) =>
    sendJson<SchemaOut>(`/schemas/from-template/${encodeURIComponent(key)}`, "POST"),

  /**
   * PUT replaces the field list wholesale (contract, "Schemas"): once fields
   * can be reordered or renamed there is no unambiguous merge for a partial
   * update, and the editor always holds the complete list anyway.
   */
  update: (id: string, body: SchemaWrite) =>
    sendJson<SchemaOut>(`/schemas/${encodeURIComponent(id)}`, "PUT", body),

  /**
   * 204, no body. Uploads converted against this schema keep working: each
   * stored result carries its own schema snapshot.
   */
  remove: async (id: string) => {
    await request(`/schemas/${encodeURIComponent(id)}`, { method: "DELETE" });
  },
};

/* ---------------------------------------------------------------- Uploads */

export const uploads = {
  create: async (file: File, schemaId: string): Promise<UploadOut> => {
    const form = new FormData();
    form.append("file", file);
    form.append("schema_id", schemaId);
    // No Content-Type header: the browser must set the multipart boundary.
    const response = await request("/uploads", { method: "POST", body: form });
    return (await response.json()) as UploadOut;
  },

  list: () => getJson<UploadOut[]>("/uploads"),

  get: (id: string) => getJson<UploadOut>(`/uploads/${encodeURIComponent(id)}`),

  result: (id: string, page?: { limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (page?.limit !== undefined) query.set("limit", String(page.limit));
    if (page?.offset !== undefined) query.set("offset", String(page.offset));
    const suffix = query.size ? `?${query}` : "";
    return getJson<ResultOut>(`/uploads/${encodeURIComponent(id)}/result${suffix}`);
  },

  overrideMapping: (id: string, mapping: MappingOverride["mapping"]) =>
    sendJson<UploadOut>(`/uploads/${encodeURIComponent(id)}/mapping`, "PUT", {
      mapping,
    } satisfies MappingOverride),

  /**
   * Fetched as a blob rather than navigated to, so the request carries the
   * session cookie through the dev proxy (a document navigation would be
   * bypassed to index.html) and so a failure surfaces as a normal ApiError.
   */
  exportFile: async (id: string, format: ExportFormat): Promise<Blob> => {
    const response = await request(
      `/uploads/${encodeURIComponent(id)}/export?format=${format}`,
    );
    return await response.blob();
  },
};

/** Saves a blob under `filename` using a transient object URL. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Human-readable text for anything thrown by this module. */
export function describeError(error: unknown): string {
  const devHint = import.meta.env.DEV ? " Is the backend running on port 8000?" : "";
  if (error instanceof NetworkError) {
    return `Could not reach the Sheetwright API.${devHint}`;
  }
  if (error instanceof ApiError) {
    return error.status >= 500 ? `${error.message}${devHint}` : error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
