// Typy odpowiedzi GREGAI wg api_contract.md (GREGAI 1.45.17).
// Pola dynamiczne sa celowo luźne (unknown), żeby pomost nie kruszył się
// na nowych polach serwera; kluczowe kształty są opisane.

// --- Rozmowa ---

export interface ChatHistoryEntry {
  role: string;
  content: string;
}

export interface PendingJob {
  pending_job: string;
}

export interface ChatFinal {
  speech?: string;
  kind?: string;
  card?: unknown;
  provider?: string | null;
  model_active?: boolean;
  sig?: string;
  pending_action?: unknown;
  pending_clarify?: unknown[] | null;
  suggested_node?: unknown;
  graph_changed?: boolean;
  wezly_auto?: boolean;
  wezly_since?: number;
}

export type ChatResponse = ChatFinal | PendingJob;

export interface ProgressResponse {
  events?: unknown[];
  total?: number;
  done?: boolean;
}

// --- Notatki i graf ---

export interface NoteSummary {
  id: string;
  tytul: string;
  typ: string;
  modyfikacja?: string;
  okladka?: string;
}

export interface NoteDetail {
  id: string;
  title: string;
  type: string;
  text?: string;
  body?: string;
  version?: string;
  modyfikacja?: string;
  readonly?: boolean;
  readonly_reason?: string | null;
}

export interface GraphNode {
  id: string;
  title: string;
  type: string;
  excerpt?: string;
  modyfikacja?: string;
  links?: number;
  readonly?: boolean;
  readonly_reason?: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  errors?: unknown[];
  skipped?: unknown[];
}

// --- System ---

export interface HealthData {
  ok?: boolean;
  generated_at?: string;
  version?: string;
  service?: Record<string, unknown>;
  system?: Record<string, unknown>;
  koryto?: Record<string, unknown>;
  vault?: Record<string, unknown>;
  wezly?: Record<string, unknown>;
  profil?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SystemInfo {
  host?: unknown;
  ollama?: unknown;
  ollama_model?: string;
  router?: unknown;
  koryto?: unknown;
  cloud?: unknown;
  juggler?: unknown;
  straz?: unknown;
  budzet?: unknown;
  warp?: unknown;
  student?: unknown;
  planner?: unknown;
  warm?: unknown;
  ollama_sesja?: unknown;
  sysop?: unknown;
  version?: string;
  lan?: unknown;
  project_root?: string;
  service?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface StatusData {
  model_active?: boolean;
  straz?: boolean;
  usd?: Record<string, unknown> | null;
  straz_blad?: string | boolean;
}

// --- Zadania stale ---

export interface StandingTask {
  plik?: string;
  nazwa?: string;
  status?: string;
  zlecenie?: string;
  interwal_minut?: number;
  utworzono?: string;
  ostatnie?: string | null;
  nastepne?: string | null;
  alertow?: number;
  dziennik?: unknown;
  [key: string]: unknown;
}

export interface StandingList {
  zadania: StandingTask[];
}

export interface StandingAction {
  ok?: boolean;
  why?: string | null;
  plik?: string | null;
  interwal_minut?: number | null;
  speech?: string | null;
  [key: string]: unknown;
}

// --- Monitorowanie ---

export interface KorytoCall {
  ts?: string;
  kto?: string;
  etap?: string;
  narzedzie?: string | null;
  sekund?: number | null;
}

export interface KorytoHistory {
  wywolania: KorytoCall[];
  wywolania_dzis?: Record<string, unknown>;
}

export interface StrazEntry {
  ts?: string;
  co?: string;
  ocena?: string;
  poziom?: string;
  [key: string]: unknown;
}

export interface StrazHistory {
  wpisy: StrazEntry[];
  wyciszone?: unknown;
}

export interface BudgetSpend {
  ts?: string;
  model?: string;
  wejscie?: number;
  wyjscie?: number;
  usd?: number;
}

export interface BudgetData {
  budzet?: Record<string, unknown> | null;
  wydatki: BudgetSpend[];
}

export interface ModelLogEntry {
  ts?: string;
  model?: string;
  sekund?: number;
  tok_s?: number;
  tokeny?: unknown;
  [key: string]: unknown;
}

export interface ModelsLog {
  inferencje: ModelLogEntry[];
}

export interface DecisionLogEntry {
  ts?: string;
  stage?: string;
  message?: string;
  tool?: string | null;
  took_ms?: number | null;
  model_active?: string | null;
  extra?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DecisionLog {
  entries: DecisionLogEntry[];
}

// --- Profil i zrodla ---

export interface ProfileEnvelope {
  exists?: boolean;
  profile?: Record<string, unknown> | null;
}

export interface SourcesData {
  chat?: string;
  foldery?: string[];
  wgrane?: unknown[];
  wgrane_katalog?: string;
  limit?: number;
  [key: string]: unknown;
}

export interface SourcesAction {
  ok?: boolean;
  why?: string | null;
  status?: unknown;
  [key: string]: unknown;
}

export interface UploadResult {
  ok?: boolean;
  name?: string;
  size?: number;
  [key: string]: unknown;
}

// --- Siec i evaluacja ---

export interface DiagnozaLayer {
  nazwa?: string;
  ok?: boolean;
  szczegoly?: string;
  ms?: number | null;
  rada?: string | null;
  [key: string]: unknown;
}

export interface DiagnozaData {
  internet?: boolean;
  werdykt?: string;
  naprawa?: string | null;
  czas_s?: number;
  warstwy?: DiagnozaLayer[];
  [key: string]: unknown;
}

export interface NetworkDevices {
  urzadzenia?: unknown[];
  skan?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface EvalRecord {
  ts?: string;
  tryb?: string;
  wersja?: string;
  przypadki?: number;
  zaliczone?: number;
}

export interface EvalHistory {
  rekordy: EvalRecord[];
  uruchomienie?: Record<string, unknown>;
}

export interface EvalRun {
  started?: boolean;
  [key: string]: unknown;
}
