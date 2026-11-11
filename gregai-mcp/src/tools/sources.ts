// Zrodla rozmowy GREGAI: foldery lokalne i wgrane pliki (per rozmowa).
// Kontrakt: GET /api/sources?chat=, POST /api/sources {chat, dodaj|usun},
// POST /api/upload {chat, name, data_base64}.

import { GregaiClient } from "../client.js";
import { type McpToolDef, mcpJson, requiredString, safe } from "./common.js";
import type { SourcesAction, SourcesData, UploadResult } from "../types.js";

export function sourcesTools(client: GregaiClient): McpToolDef[] {
  return [
    {
      name: "sources_get",
      description:
        "Zrodla rozmowy GREGAI: foldery, wgrane pliki i ich katalog, limit. " +
        "Identyfikator rozmowy (chat) jest umowny; ten sam id odtwarza ta sama liste.",
      inputSchema: {
        type: "object",
        properties: {
          chat: { type: "string", description: "Identyfikator rozmowy." },
        },
        required: ["chat"],
      },
      handler: async (args) => {
        const chat = requiredString(args, "chat");
        if (!chat) return mcpJson({ error: "Brak identyfikatora rozmowy (chat)." });
        return mcpJson(await safe(() => client.get<SourcesData>(`/api/sources?chat=${encodeURIComponent(chat)}`)));
      },
    },
    {
      name: "sources_add",
      description:
        "Dodaj folder lokalny do zrodel rozmowy GREGAI (agent czyta te sciezke w tej rozmowie). " +
        "Odpowiedz {ok, why, status}; odmowa zawsze z polskim powodem.",
      inputSchema: {
        type: "object",
        properties: {
          chat: { type: "string", description: "Identyfikator rozmowy." },
          sciezka: { type: "string", description: "Sciezka folderu do dodania." },
        },
        required: ["chat", "sciezka"],
      },
      handler: async (args) => {
        const chat = requiredString(args, "chat");
        const sciezka = requiredString(args, "sciezka");
        if (!chat) return mcpJson({ error: "Brak identyfikatora rozmowy (chat)." });
        if (!sciezka) return mcpJson({ error: "Brak sciezki folderu (sciezka)." });
        return mcpJson(await safe(() => client.post<SourcesAction>("/api/sources", { chat, dodaj: sciezka })));
      },
    },
    {
      name: "sources_remove",
      description: "Usun folder ze zrodel rozmowy GREGAI.",
      inputSchema: {
        type: "object",
        properties: {
          chat: { type: "string", description: "Identyfikator rozmowy." },
          sciezka: { type: "string", description: "Sciezka folderu do usuniecia." },
        },
        required: ["chat", "sciezka"],
      },
      handler: async (args) => {
        const chat = requiredString(args, "chat");
        const sciezka = requiredString(args, "sciezka");
        if (!chat) return mcpJson({ error: "Brak identyfikatora rozmowy (chat)." });
        if (!sciezka) return mcpJson({ error: "Brak sciezki folderu (sciezka)." });
        return mcpJson(await safe(() => client.post<SourcesAction>("/api/sources", { chat, usun: sciezka })));
      },
    },
    {
      name: "upload",
      description:
        "Wgraj plik (base64) jako zalacznik rozmowy GREGAI; potem uzyj nazwy w gregai_chat.files. " +
        "Limit serwera 25 MB; cialo JSON wiec dane base64 (rozmiar rosnie ~4/3).",
      inputSchema: {
        type: "object",
        properties: {
          chat: { type: "string", description: "Identyfikator rozmowy." },
          name: { type: "string", description: "Nazwa pliku (z rozszerzeniem)." },
          data_base64: { type: "string", description: "Zawartosc pliku w base64." },
        },
        required: ["chat", "name", "data_base64"],
      },
      handler: async (args) => {
        const chat = requiredString(args, "chat");
        const name = requiredString(args, "name");
        const data_base64 = String(args.data_base64 ?? "");
        if (!chat) return mcpJson({ error: "Brak identyfikatora rozmowy (chat)." });
        if (!name) return mcpJson({ error: "Brak nazwy pliku (name)." });
        if (!data_base64) return mcpJson({ error: "Brak zawartosci (data_base64)." });
        return mcpJson(
          await safe(() => client.post<UploadResult>("/api/upload", { chat, name, data_base64 })),
        );
      },
    },
  ];
}
