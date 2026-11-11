// Klient HTTP GREGAI (api_contract.md). Czysty fetch - zero zmian w GREGAI.
// Autoryzacja: localhost bez tokenu; LAN z naglowkiem X-Gregai-Token.
// Timeouty: 30 s domyslnie, 120 s dla rozmowy. Retry: 1 raz przy 5xx.

import { randomUUID } from "node:crypto";

export const DEFAULT_TIMEOUT_MS = 30_000;
export const CHAT_TIMEOUT_MS = 120_000;

export interface GregaiClientOptions {
  baseUrl?: string;
  token?: string;
}

export class GregaiApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown = null) {
    super(message);
    this.name = "GregaiApiError";
    this.status = status;
    this.payload = payload;
  }
}

export function errText(e: unknown): string {
  if (e instanceof GregaiApiError) {
    const msg = payloadErrorMessage(e.payload) ?? e.message;
    return e.status > 0 ? `GREGAI HTTP ${e.status}: ${msg}` : msg;
  }
  return e instanceof Error ? e.message : String(e);
}

function payloadErrorMessage(payload: unknown): string | null {
  if (isRecord(payload) && typeof payload.error === "string") return payload.error;
  return null;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function withQuery(
  path: string,
  params: Record<string, string | number | undefined | null>,
): string {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    sp.set(key, String(value));
  }
  const q = sp.toString();
  return q ? `${path}?${q}` : path;
}

interface RequestOptions {
  body?: unknown;
  timeoutMs?: number;
  retries?: number;
}

export interface SseEvent {
  event: string;
  data: string;
}

export interface SseSummary {
  events: SseEvent[];
  token_count: number;
  token_chars: number;
  done: boolean;
  err: string | null;
  error: string | null;
}

export class GregaiClient {
  readonly baseUrl: string;
  private readonly token: string;

  constructor(options: GregaiClientOptions = {}) {
    const raw = options.baseUrl ?? process.env.GREGAI_URL ?? "http://127.0.0.1:7777";
    this.baseUrl = raw.replace(/\/+$/, "");
    this.token = options.token ?? process.env.GREGAI_TOKEN ?? "";
  }

  url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  private headers(method: string): Record<string, string> {
    const h: Record<string, string> = { Accept: "application/json" };
    if (method !== "GET") h["Content-Type"] = "application/json";
    if (this.token) h["X-Gregai-Token"] = this.token;
    return h;
  }

  async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const { body, timeoutMs = DEFAULT_TIMEOUT_MS, retries = 1 } = options;
    let attempt = 0;
    for (;;) {
      let res: Response;
      try {
        res = await fetch(this.url(path), {
          method,
          headers: this.headers(method),
          body: method === "GET" ? undefined : JSON.stringify(body ?? {}),
          signal: AbortSignal.timeout(timeoutMs),
        });
      } catch (e) {
        throw new GregaiApiError(
          `Nie udalo sie polaczyc z GREGAI (${this.baseUrl}): ${errText(e)}`,
          0,
        );
      }
      if (res.status >= 500 && attempt < retries) {
        attempt += 1;
        continue;
      }
      const raw = await res.text();
      let data: unknown = null;
      if (raw) {
        try {
          data = JSON.parse(raw);
        } catch {
          throw new GregaiApiError(
            `Odpowiedz GREGAI nie jest JSON-em (HTTP ${res.status}).`,
            res.status,
            raw.slice(0, 300),
          );
        }
      }
      if (!res.ok) {
        const msg = payloadErrorMessage(data) ?? `kod ${res.status}`;
        throw new GregaiApiError(msg, res.status, data);
      }
      return data as T;
    }
  }

  get<T>(path: string, options: RequestOptions = {}): Promise<T> {
    return this.request<T>("GET", path, options);
  }

  post<T>(path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
    return this.request<T>("POST", path, { ...options, body });
  }

  /**
   * Podglad strumienia SSE /api/chat/stream (fetch + ReadableStream, bez
   * EventSource - nie istnieje w Node). Wynik jest TYLKO podgladem:
   * kanoniczna odpowiedz zawsze z /api/chat/wait.
   */
  async readStream(job: string, timeoutMs = CHAT_TIMEOUT_MS): Promise<SseSummary> {
    const summary: SseSummary = {
      events: [],
      token_count: 0,
      token_chars: 0,
      done: false,
      err: null,
      error: null,
    };
    let res: Response;
    try {
      res = await fetch(this.url(withQuery("/api/chat/stream", { job })), {
        headers: { Accept: "text/event-stream", ...(this.token ? { "X-Gregai-Token": this.token } : {}) },
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (e) {
      summary.error = errText(e);
      return summary;
    }
    if (!res.ok) {
      summary.error = `HTTP ${res.status}`;
      const text = await res.text().catch(() => "");
      try {
        const data = JSON.parse(text) as { error?: string };
        if (typeof data.error === "string") summary.error = data.error;
      } catch {
        // Podglad tylko; nie chcemy zabijac wyniku.
      }
      return summary;
    }
    if (!res.body) {
      summary.error = "Brak strumienia SSE.";
      return summary;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf = (buf + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");
        for (;;) {
          const idx = buf.indexOf("\n\n");
          if (idx < 0) break;
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const ev = parseSseFrame(frame);
          if (!ev) continue;
          summary.events.push(ev);
          if (ev.event === "token") {
            summary.token_count += 1;
            try {
              const data = JSON.parse(ev.data) as { t?: string };
              if (typeof data.t === "string") summary.token_chars += data.t.length;
            } catch {
              // Podglad tylko.
            }
          } else if (ev.event === "done") {
            summary.done = true;
            return summary;
          } else if (ev.event === "err") {
            try {
              const data = JSON.parse(ev.data) as { error?: string };
              summary.err = typeof data.error === "string" ? data.error : ev.data;
            } catch {
              summary.err = ev.data;
            }
            return summary;
          }
        }
      }
    } catch (e) {
      summary.error = errText(e);
    }
    return summary;
  }
}

function parseSseFrame(frame: string): SseEvent | null {
  let event = "message";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += (data ? "\n" : "") + line.slice(5).trim();
  }
  if (event === "message" && !data) return null;
  return { event, data };
}

/** Idempotencja gregai_chat: client_id podany przez klienta albo UUID v4. */
export function chatClientId(args: Record<string, unknown>): string {
  const given = typeof args.client_id === "string" ? args.client_id.trim() : "";
  return given || randomUUID();
}
