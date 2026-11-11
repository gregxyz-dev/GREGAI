// Monitorowanie GREGAI: historia Koryta, historia Strazy, budzet dzienny,
// log inferencji modeli, dziennik decyzji routera.

import { GregaiClient, withQuery } from "../client.js";
import { type McpToolDef, mcpJson, optInt, optString, safe } from "./common.js";
import type { BudgetData, DecisionLog, KorytoHistory, ModelsLog, StrazHistory } from "../types.js";

export function monitorTools(client: GregaiClient): McpToolDef[] {
  return [
    {
      name: "koryto_history",
      description:
        "Historia wywolan Koryta (lancucha dostawcow): {wywolania: [{ts, kto, etap, narzedzie, " +
        "sekund}], wywolania_dzis}. Limit serwera 1-100, domyślnie 20.",
      inputSchema: {
        type: "object",
        properties: {
          limit: { type: "number", description: "Liczba wpisow (domyślnie 20)." },
        },
      },
      handler: async (args) =>
        mcpJson(
          await safe(() =>
            client.get<KorytoHistory>(
              withQuery("/api/koryto/historia", { limit: optInt(args.limit, 20, 1, 100) }),
            ),
          ),
        ),
    },
    {
      name: "straz_history",
      description:
        "Historia alertow Strazy systemu: {wpisy: [{ts, co, ocena, poziom}], wyciszone}. " +
        "Limit serwera 1-200, domyślnie 50; mozna filtrowac poziomem.",
      inputSchema: {
        type: "object",
        properties: {
          limit: { type: "number", description: "Liczba wpisow (domyślnie 50)." },
          poziom: {
            type: "string",
            description: 'Filtr poziomu alertu; wartości jak w historii: "średnie", "wysokie", "inne".',
          },
        },
      },
      handler: async (args) =>
        mcpJson(
          await safe(() =>
            client.get<StrazHistory>(
              withQuery("/api/straz/historia", {
                limit: optInt(args.limit, 50, 1, 200),
                poziom: optString(args, "poziom"),
              }),
            ),
          ),
        ),
    },
    {
      name: "budget",
      description:
        "Dzienny budzet Koryta: {budzet: {...}, wydatki: [{ts, model, wejscie, wyjscie, usd}]} " +
        "za dzis (UTC).",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.get<BudgetData>("/api/budget/daily"))),
    },
    {
      name: "models_log",
      description:
        "Log inferencji modeli lokalnych: {inferencje: [{ts, model, sekund, tok_s, tokeny}]}. " +
        "Limit serwera 1-50.",
      inputSchema: {
        type: "object",
        properties: {
          limit: { type: "number", description: "Liczba wpisow (domyślnie 20)." },
        },
      },
      handler: async (args) =>
        mcpJson(
          await safe(() =>
            client.get<ModelsLog>(
              withQuery("/api/models/log", { limit: optInt(args.limit, 20, 1, 50) }),
            ),
          ),
        ),
    },
    {
      name: "decision_log",
      description:
        "Dziennik decyzji routera GREGAI (Nadzorca): {entries: [{ts, stage, message, tool, " +
        "took_ms, model_active, extra}]}. Serwer zwraca do 200 wpisow; limit tnie od najnowszych.",
      inputSchema: {
        type: "object",
        properties: {
          limit: { type: "number", description: "Liczba wpisow (domyślnie 30)." },
        },
      },
      handler: async (args) => {
        const limit = optInt(args.limit, 30, 1, 200);
        const payload = await safe(() => client.get<DecisionLog>("/api/debug/log"));
        if ("entries" in payload && Array.isArray(payload.entries)) {
          return mcpJson({ entries: payload.entries.slice(0, limit) });
        }
        return mcpJson(payload);
      },
    },
  ];
}
