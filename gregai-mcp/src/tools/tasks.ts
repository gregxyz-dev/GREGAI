// Zadania stale GREGAI (standing tasks): lista, tworzenie (komenda naturalna
// z interwalem, np. "co 30 minut sprawdź pocztę"), pauza/wznowienie, usuwanie,
// czyszczenie dziennika. Uwaga: API tworzy zadania z pola "komenda"; pauza
// przyjmuje stan "wstrzymane" albo "aktywne".

import { GregaiClient } from "../client.js";
import { type McpToolDef, mcpJson, requiredString, safe } from "./common.js";
import type { StandingAction, StandingList } from "../types.js";

export function tasksTools(client: GregaiClient): McpToolDef[] {
  return [
    {
      name: "standing_list",
      description:
        "Lista zadan stalych GREGAI: {zadania: [{plik, nazwa, status, zlecenie, interwal_minut, " +
        "utworzono, ostatnie, nastepne, alertow, dziennik}]}.",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.get<StandingList>("/api/standing"))),
    },
    {
      name: "standing_create",
      description:
        "Utworz zadanie stale GREGAI z komendy naturalnej, np. 'co 30 minut sprawdź pocztę' albo " +
        "'codziennie o 8 rano przypomnij o przeglądzie'. Interwal parsuje GREGAI; odpowiedz zawiera " +
        "plik, interwal_minut i speech. (Pierwotna specyfikacja mowila o nazwa/zlecenie/interwal_minut " +
        "jako osobnych polach - API v1.45.17 przyjmuje jedno pole komenda.)",
      inputSchema: {
        type: "object",
        properties: {
          komenda: { type: "string", description: "Pelna tresc zadania stalego z interwalem." },
        },
        required: ["komenda"],
      },
      handler: async (args) => {
        const komenda = requiredString(args, "komenda");
        if (!komenda) return mcpJson({ error: "Brak tresci zadania (komenda)." });
        return mcpJson(await safe(() => client.post<StandingAction>("/api/standing/nowe", { komenda })));
      },
    },
    {
      name: "standing_pause",
      description:
        'Wstrzymaj albo wznow zadanie stale GREGAI. stan = "wstrzymane" (pauza) albo "aktywne" ' +
        '(wznowienie). Pole plik pochodzi z gregai_standing_list.',
      inputSchema: {
        type: "object",
        properties: {
          plik: { type: "string", description: "Nazwa pliku zadania (z gregai_standing_list)." },
          stan: {
            type: "string",
            enum: ["wstrzymane", "aktywne"],
            description: '"wstrzymane" = pauza, "aktywne" = wznowienie.',
          },
        },
        required: ["plik", "stan"],
      },
      handler: async (args) => {
        const plik = requiredString(args, "plik");
        const stan = requiredString(args, "stan");
        if (!plik) return mcpJson({ error: "Brak nazwy pliku zadania (plik)." });
        return mcpJson(await safe(() => client.post<StandingAction>("/api/standing/pauza", { plik, stan })));
      },
    },
    {
      name: "standing_delete",
      description: "Usun zadanie stale GREGAI (plik z gregai_standing_list).",
      inputSchema: {
        type: "object",
        properties: {
          plik: { type: "string", description: "Nazwa pliku zadania." },
        },
        required: ["plik"],
      },
      handler: async (args) => {
        const plik = requiredString(args, "plik");
        if (!plik) return mcpJson({ error: "Brak nazwy pliku zadania (plik)." });
        return mcpJson(await safe(() => client.post<StandingAction>("/api/standing/usun", { plik })));
      },
    },
    {
      name: "standing_clear",
      description: "Wyczysc dziennik wykonań zadania stalego GREGAI (bez usuwania zadania).",
      inputSchema: {
        type: "object",
        properties: {
          plik: { type: "string", description: "Nazwa pliku zadania." },
        },
        required: ["plik"],
      },
      handler: async (args) => {
        const plik = requiredString(args, "plik");
        if (!plik) return mcpJson({ error: "Brak nazwy pliku zadania (plik)." });
        return mcpJson(await safe(() => client.post<StandingAction>("/api/standing/wyczysc", { plik })));
      },
    },
  ];
}
