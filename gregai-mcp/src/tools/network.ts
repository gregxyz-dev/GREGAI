// Siec lokalna i diagnostyka lacznosci GREGAI: /api/network/devices,
// /api/network/scan, /api/diagnoza.

import { GregaiClient } from "../client.js";
import { type McpToolDef, mcpJson, safe } from "./common.js";
import type { DiagnozaData, NetworkDevices } from "../types.js";

export function networkTools(client: GregaiClient): McpToolDef[] {
  return [
    {
      name: "network_devices",
      description:
        "Urzadzenia widziane przez GREGAI w sieci LAN: {urzadzenia: [...], skan: {...}} " +
        "(pole skan.running = czy skan trwa).",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.get<NetworkDevices>("/api/network/devices"))),
    },
    {
      name: "network_scan",
      description:
        "Uruchom skan sieci LAN w GREGAI. Odpowiedz {started}: true = skan sie zaczal " +
        "(wynik potem w gregai_network_devices).",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.post<unknown>("/api/network/scan"))),
    },
    {
      name: "diagnoza",
      description:
        "Diagnoza lacznosci GREGAI z internetem: {internet, werdykt, naprawa, czas_s, " +
        "warstwy: [{nazwa, ok, szczegoly, ms, rada}]}. Jako jedyna wystaje do sieci (z WARP).",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.get<DiagnozaData>("/api/diagnoza"))),
    },
  ];
}
