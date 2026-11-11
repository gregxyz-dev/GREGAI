// Evaluacja GREGAI: historia przebiegow z training/ewaluacja/regresja.jsonl
// i uruchomienie eval w tle. Uwaga: /api/eval/run nie przyjmuje parametrow
// (pierwotna specyfikacja mowila o id/zywo - API v1.45.17 uruchamia standardowy
// regresyjny eval).

import { GregaiClient, withQuery } from "../client.js";
import { type McpToolDef, mcpJson, optInt, safe } from "./common.js";
import type { EvalHistory, EvalRun } from "../types.js";

export function evalTools(client: GregaiClient): McpToolDef[] {
  return [
    {
      name: "eval_history",
      description:
        "Historia evaluacji GREGAI: {rekordy: [{ts, tryb, wersja, przypadki, zaliczone}], " +
        "uruchomienie}. Limit serwera 1-50, domyślnie 10.",
      inputSchema: {
        type: "object",
        properties: {
          limit: { type: "number", description: "Liczba rekordow (domyślnie 10)." },
        },
      },
      handler: async (args) =>
        mcpJson(
          await safe(() =>
            client.get<EvalHistory>(
              withQuery("/api/eval/history", { limit: optInt(args.limit, 10, 1, 50) }),
            ),
          ),
        ),
    },
    {
      name: "eval_run",
      description:
        "Uruchom eval regresyjny GREGAI w tle. Odpowiedz {started}: true = start, " +
        "false = eval juz trwa (status w gregai_eval_history).",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.post<EvalRun>("/api/eval/run"))),
    },
  ];
}
