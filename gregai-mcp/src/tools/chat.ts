// Rozmowa z GREGAI: gregai_chat (czekanie na final), gregai_chat_wait,
// gregai_chat_cancel. Kontrakt: /api/chat -> {pending_job} albo finalny
// kszalt; kanoniczny wynik zawsze z /api/chat/wait; stream i progress to
// podglad narracji Namyslu.

import { randomUUID } from "node:crypto";

import {
  CHAT_TIMEOUT_MS,
  GregaiClient,
  errText,
  sleep,
  withQuery,
  type SseSummary,
} from "../client.js";
import {
  type McpToolDef,
  mcpJson,
  safe,
} from "./common.js";
import type { ChatFinal, ChatResponse, ProgressResponse } from "../types.js";

interface WaitOutcome {
  result?: ChatFinal;
  error?: string;
}

export function chatTools(client: GregaiClient): McpToolDef[] {
  return [
    {
      name: "chat",
      description:
        "Wyslij wiadomosc do lokalnego asystenta GREGAI (localhost:7777) i odbierz finalna odpowiedz. " +
        "Gdy GREGAI dlugo mysli (Namysl), narzedzie samo czeka do 120 s i dolacza zdarzenia faz " +
        "(progress_events) oraz podglad strumienia (stream).",
      inputSchema: {
        type: "object",
        properties: {
          message: { type: "string", description: "Tresc wiadomosci do GREGAI." },
          history: {
            type: "array",
            items: { type: "object" },
            description: "Kontekst rozmowy: [{role: 'user'|'assistant', content}].",
          },
          project: { type: "string", description: "Slug projektu GREGAI (opcjonalnie)." },
          files: {
            type: "array",
            items: { type: "string" },
            description: "Nazwy wgranych plikow tej rozmowy (opcjonalnie).",
          },
          client_id: {
            type: "string",
            description: "Identyfikator idempotencji (UUID v4); generowany automatycznie.",
          },
          pending_action: {
            type: "object",
            description: "Potwierdzenie karty zgody z poprzedniej odpowiedzi: {id} + wiadomość 'tak'/'nie'. Bez tego agent OpenCode nie dokończy akcji wymagających zgody.",
          },
          pending_clarify: {
            type: "array",
            items: { type: "object" },
            description: "Odpowiedzi na pytania doprecyzowujące z poprzedniej odpowiedzi.",
          },
        },
        required: ["message"],
      },
      handler: async (args) => {
        const message = String(args.message ?? "");
        if (!message.trim()) return mcpJson({ error: "Wiadomosc nie moze byc pusta." });

        const rawHistory = Array.isArray(args.history) ? args.history : [];
        const history = rawHistory
          .map((entry) => {
            const rec = (entry ?? {}) as Record<string, unknown>;
            return { role: String(rec.role ?? "user"), content: String(rec.content ?? "") };
          })
          .filter((h) => h.content.trim() !== "");
        const project = typeof args.project === "string" ? args.project.trim() || undefined : undefined;
        const files = Array.isArray(args.files) ? args.files.map((f) => String(f)) : [];
        const client_id =
          typeof args.client_id === "string" && args.client_id.trim() !== ""
            ? args.client_id.trim()
            : randomUUID();
        const pendingAction = (args.pending_action && typeof args.pending_action === "object" && !Array.isArray(args.pending_action))
          ? args.pending_action
          : undefined;
        const pendingClarify = Array.isArray(args.pending_clarify) ? args.pending_clarify : undefined;

        const body: Record<string, unknown> = { message, client_id };
        if (history.length) body.history = history;
        if (project) body.project = project;
        if (files.length) body.files = files;
        if (pendingAction) body.pending_action = pendingAction;
        if (pendingClarify) body.pending_clarify = pendingClarify;

        const first = await safe(() => client.post<ChatResponse>("/api/chat", body, { timeoutMs: CHAT_TIMEOUT_MS }));
        if ("error" in first) return mcpJson(first);

        if (!("pending_job" in first)) {
          return mcpJson({ ...first, progress_events: [] });
        }

        const job = first.pending_job;
        const [waitRes, progressRes, streamRes] = await Promise.allSettled([
          waitLoop(client, job),
          progressLoop(client, job),
          client.readStream(job),
        ]);

        const progress = progressRes.status === "fulfilled" ? progressRes.value : [];
        const stream: Record<string, unknown> =
          streamRes.status === "fulfilled" ? summarizeStream(streamRes.value) : { error: "Podglad strumienia nieudany." };

        if (waitRes.status === "rejected") {
          return mcpJson({
            error: errText(waitRes.reason),
            job,
            progress_events: progress,
            hint: "Zadanie moze wciaz trwac na serwerze: dopytaj gregai_chat_wait (job), a zanim odpowie - gregai_chat_cancel.",
          });
        }
        const waited = waitRes.value;
        if (waited.result) {
          return mcpJson({ ...waited.result, job, progress_events: progress, stream });
        }
        return mcpJson({
          error: waited.error ?? "Nie otrzymano finalnej odpowiedzi.",
          job,
          progress_events: progress,
          stream,
          hint: "Zadanie moze wciaz trwac: dopytaj gregai_chat_wait albo przerwij gregai_chat_cancel.",
        });
      },
    },
    {
      name: "chat_wait",
      description:
        "Dopytaj o wynik trwajacego zadania GREGAI (pending_job z gregai_chat). Zwraca finalna odpowiedz " +
        "albo {pending_job}, gdy model wciaz liczy. To jedyne kanoniczne zrodlo wyniku.",
      inputSchema: {
        type: "object",
        properties: {
          job: { type: "string", description: "Identyfikator zadania (pending_job)." },
        },
        required: ["job"],
      },
      handler: async (args) => {
        const job = String(args.job ?? "").trim();
        if (!job) return mcpJson({ error: "Brak identyfikatora zadania (job)." });
        return mcpJson(await safe(() => client.post<ChatResponse>("/api/chat/wait", { job })));
      },
    },
    {
      name: "chat_cancel",
      description: "Anuluj trwajace zadanie GREGAI (pending_job z gregai_chat).",
      inputSchema: {
        type: "object",
        properties: {
          job: { type: "string", description: "Identyfikator zadania (pending_job)." },
        },
        required: ["job"],
      },
      handler: async (args) => {
        const job = String(args.job ?? "").trim();
        if (!job) return mcpJson({ error: "Brak identyfikatora zadania (job)." });
        return mcpJson(await safe(() => client.post<unknown>("/api/chat/cancel", { job })));
      },
    },
  ];
}

async function waitLoop(client: GregaiClient, job: string, deadlineMs = CHAT_TIMEOUT_MS): Promise<WaitOutcome> {
  const start = Date.now();
  for (;;) {
    const r = await client.post<ChatResponse>("/api/chat/wait", { job });
    if (!("pending_job" in r)) return { result: r };
    if (Date.now() - start >= deadlineMs) {
      return { error: `Przekroczono ${Math.round(deadlineMs / 1000)} s oczekiwania na GREGAI.` };
    }
    await sleep(3000);
  }
}

async function progressLoop(client: GregaiClient, job: string, deadlineMs = CHAT_TIMEOUT_MS): Promise<unknown[]> {
  const events: unknown[] = [];
  const start = Date.now();
  let since = 0;
  for (;;) {
    if (Date.now() - start >= deadlineMs) break;
    try {
      const r = await client.get<ProgressResponse>(withQuery("/api/chat/progress", { job, since }));
      const fresh = Array.isArray(r.events) ? r.events : [];
      events.push(...fresh);
      since = typeof r.total === "number" ? r.total : since + fresh.length;
      if (r.done) break;
    } catch {
      break; // Podglad nie moze zabic wyniku.
    }
    await sleep(2000);
  }
  return events;
}

function summarizeStream(s: SseSummary): Record<string, unknown> {
  return {
    done: s.done,
    err: s.err,
    error: s.error,
    tokens: s.token_count,
    chars: s.token_chars,
  };
}
