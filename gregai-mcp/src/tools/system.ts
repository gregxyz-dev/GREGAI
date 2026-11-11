// Stan systemu GREGAI: /api/health, /api/system_info, /api/status.

import { GregaiClient } from "../client.js";
import { type McpToolDef, mcpJson, safe } from "./common.js";
import type { HealthData, StatusData, SystemInfo } from "../types.js";

export function systemTools(client: GregaiClient): McpToolDef[] {
  return [
    {
      name: "health",
      description:
        "Zdrowie GREGAI: {ok, generated_at, version, service, system, koryto, vault, wezly, profil}. " +
        "Bez tresci notatek i sekretow - bezpieczny do odczytu w sesji.",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.get<HealthData>("/api/health"))),
    },
    {
      name: "system_info",
      description:
        "Pelna diagnostyka GREGAI: host, ollama, koryto, chmura, straz, budzet, warp, student, " +
        "planner, sysop, wersja, LAN, czas dzialania uslugi. Duzy obiekt - czytaj wybiórczo.",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.get<SystemInfo>("/api/system_info"))),
    },
    {
      name: "status",
      description:
        "Pigulka stanu rozmowy: {model_active, straz, usd, straz_blad}. Lekka alternatywa " +
        "dla gregai_health, gdy chodzi tylko o dostepnosc modelu i budzet.",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.get<StatusData>("/api/status"))),
    },
  ];
}
