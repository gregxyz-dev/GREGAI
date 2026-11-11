// Profil uzytkownika GREGAI (data/profil.json): odczyt i zapis. Zapis nadpisuje
// caly profil - zawsze zaczynaj od gregai_profile_get i scalaj pola.

import { GregaiClient } from "../client.js";
import { type McpToolDef, mcpJson, safe } from "./common.js";
import type { ProfileEnvelope } from "../types.js";

export function profileTools(client: GregaiClient): McpToolDef[] {
  return [
    {
      name: "profile_get",
      description: "Odczytaj profil uzytkownika GREGAI: {exists, profile}.",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.get<ProfileEnvelope>("/api/profil"))),
    },
    {
      name: "profile_save",
      description:
        "Zapisz profil uzytkownika GREGAI (nadpisuje caly obiekt). Najpierw gregai_profile_get, " +
        "scalenie pol, dopiero zapis. Profil jest lokalny i podlega hot reload.",
      inputSchema: {
        type: "object",
        properties: {
          profile: {
            type: "object",
            description: "Pelny obiekt profilu (jak pole profile z gregai_profile_get).",
          },
        },
        required: ["profile"],
      },
      handler: async (args) => {
        const profile = args.profile as unknown;
        return mcpJson(await safe(() => client.post<ProfileEnvelope>("/api/profil", profile)));
      },
    },
  ];
}
