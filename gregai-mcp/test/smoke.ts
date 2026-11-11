// Smoke test pomostu: GREGAI musi odpowiadac na /api/health i
// /api/notes?limit=1. Nie stawia serwera MCP - sprawdza tylko lacznosc
// z zywym GREGAI (ustaw GREGAI_URL/GREGAI_TOKEN, jesli nie localhost).

import { GregaiClient, errText } from "../src/client.js";

async function main(): Promise<void> {
  const client = new GregaiClient();
  let failures = 0;

  try {
    const health = await client.get<{ ok?: boolean; version?: string }>("/api/health");
    if (health.ok === true) {
      console.log(`OK   /api/health (GREGAI ${health.version ?? "?"})`);
    } else {
      console.error(`FAIL /api/health: ${JSON.stringify(health)}`);
      failures += 1;
    }
  } catch (e) {
    console.error(`FAIL /api/health: ${errText(e)}`);
    failures += 1;
  }

  try {
    const notes = await client.get<{ notatki?: unknown[] }>("/api/notes?limit=1");
    if (Array.isArray(notes.notatki)) {
      console.log(`OK   /api/notes?limit=1 (${notes.notatki.length} notatka)`);
    } else {
      console.error(`FAIL /api/notes?limit=1: ${JSON.stringify(notes).slice(0, 200)}`);
      failures += 1;
    }
  } catch (e) {
    console.error(`FAIL /api/notes?limit=1: ${errText(e)}`);
    failures += 1;
  }

  if (failures > 0) {
    console.error(`Smoke: ${failures} bledow. Czy GREGAI dziala na ${client.baseUrl}?`);
    process.exit(1);
  }
  console.log("Smoke: wszystko OK.");
}

main().catch((e: unknown) => {
  console.error("Smoke: blad krytyczny:", e instanceof Error ? e.message : e);
  process.exit(1);
});
