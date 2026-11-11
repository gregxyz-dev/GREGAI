// Graf notatek GREGAI: wezly + krawedzie wikilinkow.

import { GregaiClient } from "../client.js";
import { type McpToolDef, mcpJson, safe } from "./common.js";
import type { GraphData } from "../types.js";

export function graphTools(client: GregaiClient): McpToolDef[] {
  return [
    {
      name: "graph",
      description:
        "Pelny graf notatek GREGAI: wezly ({id, title, type, excerpt, modyfikacja, links, readonly}) " +
        "i krawedzie wikilinkow ({source, target}). Pola errors/skipped opisuja pominieta tresc.",
      inputSchema: { type: "object", properties: {} },
      handler: async () => mcpJson(await safe(() => client.get<GraphData>("/api/graph"))),
    },
  ];
}
