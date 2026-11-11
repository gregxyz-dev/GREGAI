// Notatki GREGAI: lista, odczyt, tworzenie, edycja, usuwanie (do kosza),
// przywrocenie. Kontrakt: /api/notes, /api/note (GET/POST), /api/note/create,
// /api/note/delete, /api/note/przywroc.

import { GregaiClient, withQuery } from "../client.js";
import {
  type McpToolDef,
  mcpJson,
  optInt,
  optString,
  requiredString,
  safe,
} from "./common.js";
import type { NoteDetail, NoteSummary } from "../types.js";

export function notesTools(client: GregaiClient): McpToolDef[] {
  return [
    {
      name: "notes_list",
      description:
        "Lista notatek GREGAI z filtrami: fraza (q), typ (np. Note, Wiedza, Concept, Nauka), " +
        "zakres daty modyfikacji. Zwraca {notatki: [{id, tytul, typ, modyfikacja, okladka}]}.",
      inputSchema: {
        type: "object",
        properties: {
          q: { type: "string", description: "Fraza do wyszukania po tytule/tresci." },
          typ: { type: "string", description: "Filtr typu, np. Note, Wiedza, Concept, Nauka." },
          data: {
            type: "string",
            enum: ["dzis", "tydzien", "miesiac"],
            description: "Zakres daty modyfikacji.",
          },
          limit: { type: "number", description: "Limit wynikow (domyślnie 50)." },
        },
      },
      handler: async (args) =>
        mcpJson(
          await safe(() =>
            client.get<{ notatki: NoteSummary[] }>(
              withQuery("/api/notes", {
                q: optString(args, "q"),
                typ: optString(args, "typ"),
                data: optString(args, "data"),
                limit: optInt(args.limit, 50, 1, 200),
              }),
            ),
          ),
        ),
    },
    {
      name: "note_get",
      description:
        "Odczytaj pelna notatke GREGAI (treść Markdown + wersja bazowa do edycji). " +
        "Notatki readonly maja pole readonly_reason i nie da sie ich edytowac.",
      inputSchema: {
        type: "object",
        properties: {
          id: { type: "string", description: "Slug notatki (pole id z gregai_notes_list)." },
        },
        required: ["id"],
      },
      handler: async (args) => {
        const id = requiredString(args, "id");
        if (!id) return mcpJson({ error: "Brak id notatki." });
        return mcpJson(await safe(() => client.get<NoteDetail>(withQuery("/api/note", { id }))));
      },
    },
    {
      name: "note_create",
      description:
        'Utworz notatke GREGAI: {title, type, text}. Typy z whitelisty systemu: Note, Concept, ' +
        'Wiedza, Nauka. Tytul moze zawierac wikilinki [[...]]. 409 = duplikat tytulu.',
      inputSchema: {
        type: "object",
        properties: {
          title: { type: "string", description: "Tytul notatki." },
          type: { type: "string", description: 'Typ notatki, np. "Note", "Wiedza", "Concept", "Nauka".' },
          text: { type: "string", description: "Tresc w Markdown." },
        },
        required: ["title", "type", "text"],
      },
      handler: async (args) => {
        const title = requiredString(args, "title");
        const type = requiredString(args, "type");
        const text = String(args.text ?? "");
        if (!title) return mcpJson({ error: "Brak tytulu notatki." });
        if (!type) return mcpJson({ error: "Brak typu notatki (np. Note, Wiedza, Concept, Nauka)." });
        return mcpJson(await safe(() => client.post<unknown>("/api/note/create", { title, type, text })));
      },
    },
    {
      name: "note_update",
      description:
        "Zmien tresc notatki GREGAI. base to wersja bazowa z gregai_note_get - inna wersja daje " +
        "409 (konflikt). Zmiany tytulu takze sa wykrywane jako konflikt; treść to Markdown.",
      inputSchema: {
        type: "object",
        properties: {
          id: { type: "string", description: "Slug notatki." },
          text: { type: "string", description: "Nowa tresc (Markdown)." },
          base: { type: "string", description: "Wersja bazowa z gregai_note_get (pole version)." },
        },
        required: ["id", "text", "base"],
      },
      handler: async (args) => {
        const id = requiredString(args, "id");
        if (!id) return mcpJson({ error: "Brak id notatki." });
        const body = {
          id,
          text: String(args.text ?? ""),
          base: String(args.base ?? ""),
        };
        return mcpJson(await safe(() => client.post<unknown>("/api/note", body)));
      },
    },
    {
      name: "note_delete",
      description:
        'Usun notatke GREGAI do kosza (wymaga id i widocznego tytulu; tytul musi sie zgadzac). ' +
        "Odpowiedz podaje liczbe wisiencow (dangling_links, repointed_links) i nazwe wpisu w koszu.",
      inputSchema: {
        type: "object",
        properties: {
          id: { type: "string", description: "Slug notatki." },
          title: { type: "string", description: "Widoczny tytul notatki (musi zgadzac sie z plikiem)." },
        },
        required: ["id", "title"],
      },
      handler: async (args) => {
        const id = requiredString(args, "id");
        const title = requiredString(args, "title");
        if (!id) return mcpJson({ error: "Brak id notatki." });
        if (!title) return mcpJson({ error: "Brak tytulu notatki." });
        return mcpJson(await safe(() => client.post<unknown>("/api/note/delete", { id, title })));
      },
    },
    {
      name: "note_restore",
      description: "Przywroc notatke z kosza GREGAI (nazwa wpisu z gregai_note_delete albo kosza).",
      inputSchema: {
        type: "object",
        properties: {
          kosz: { type: "string", description: "Nazwa wpisu w koszu (pole kosz z gregai_note_delete)." },
        },
        required: ["kosz"],
      },
      handler: async (args) => {
        const kosz = requiredString(args, "kosz");
        if (!kosz) return mcpJson({ error: "Brak nazwy wpisu w koszu." });
        return mcpJson(await safe(() => client.post<unknown>("/api/note/przywroc", { kosz })));
      },
    },
  ];
}
