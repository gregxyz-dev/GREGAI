// Wspolne typy i pomocniki narzedzi MCP. Kazde narzedzie zwraca JSON
// (przy bledzie HTTP {error: string}); wyjatki nie wylatuja do MCP.

import { errText } from "../client.js";

export interface JsonSchemaProp {
  type?: string;
  description?: string;
  enum?: string[];
  items?: JsonSchemaProp;
  default?: unknown;
}

export interface JsonSchemaObject {
  type: "object";
  properties: Record<string, JsonSchemaProp>;
  required?: string[];
}

export type ToolContent = { type: "text"; text: string };

export type ToolResult = { content: ToolContent[]; isError?: boolean };

export interface McpToolDef {
  name: string;
  description: string;
  inputSchema: JsonSchemaObject;
  handler(args: Record<string, unknown>): Promise<ToolResult>;
}

/** Wynik narzedzia jako pretty JSON; pole "error" oznacza isError. */
export function mcpJson(payload: unknown): ToolResult {
  const text = JSON.stringify(payload, null, 2);
  const isError = isErrPayload(payload);
  const content: ToolContent[] = [{ type: "text", text }];
  return isError ? { content, isError: true } : { content };
}

function isErrPayload(payload: unknown): boolean {
  return (
    typeof payload === "object" &&
    payload !== null &&
    !Array.isArray(payload) &&
    "error" in payload
  );
}

/** Tarcza bledow: zlecenie HTTP -> {error: string} zamiast wyjatku. */
export async function safe<T>(fn: () => Promise<T>): Promise<T | { error: string }> {
  try {
    return await fn();
  } catch (e) {
    return { error: errText(e) };
  }
}

/** Liczba z argumentow (number albo string numeryczny), zgnieciona do zakresu. */
export function optInt(value: unknown, fallback: number, min: number, max: number): number {
  const n =
    typeof value === "number"
      ? Math.floor(value)
      : typeof value === "string" && value.trim() !== ""
        ? Math.floor(Number(value))
        : NaN;
  if (Number.isNaN(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

/** Niepusty string z argumentow albo undefined (do query parametrow). */
export function optString(args: Record<string, unknown>, key: string): string | undefined {
  const v = args[key];
  if (typeof v !== "string") return undefined;
  const trimmed = v.trim();
  return trimmed === "" ? undefined : trimmed;
}

export function requiredString(args: Record<string, unknown>, key: string): string {
  return String(args[key] ?? "").trim();
}

/** Lekka walidacja argumentow wg schematu: wymagane pola, typy, enumy. */
export function validateArgs(schema: JsonSchemaObject, args: Record<string, unknown>): string | null {
  for (const key of schema.required ?? []) {
    const v = args[key];
    if (v === undefined || v === null) return `Brak wymaganego parametru: ${key}.`;
    if (typeof v === "string" && v.trim() === "") return `Parametr ${key} nie moze byc pusty.`;
  }
  for (const [key, prop] of Object.entries(schema.properties)) {
    const v = args[key];
    if (v === undefined || v === null) continue;
    const t = prop.type ?? "string";
    if (t === "array" && !Array.isArray(v)) return `Parametr ${key} musi byc tablica.`;
    if (t === "object" && (typeof v !== "object" || Array.isArray(v))) {
      return `Parametr ${key} musi byc obiektem.`;
    }
    if (t === "number" && typeof v !== "number" && !(typeof v === "string" && !Number.isNaN(Number(v)))) {
      return `Parametr ${key} musi byc liczba.`;
    }
    if (t === "boolean" && typeof v !== "boolean") return `Parametr ${key} musi byc logiczna wartoscia (true/false).`;
    if ((t === "string" || t === "array") && typeof v !== "string" && !Array.isArray(v)) {
      return `Parametr ${key} musi byc tekstem.`;
    }
    if (prop.enum && !prop.enum.map(String).includes(String(v))) {
      return `Parametr ${key} musi byc jednym z: ${prop.enum.join(", ")}.`;
    }
  }
  return null;
}
