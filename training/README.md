# training/ - samo-trening routera GREGAI

GREGAI uczy swój własny, mały model podejmować decyzję "narzędzie czy
rozmowa" (krok 1 routingu w `agent/router.py`) na podstawie TEGO, CO SAM
PRZEŻYŁ: prawdziwych wiadomości ze śladu decyzji, fraz, które sam
zapamiętał, i opisów własnych narzędzi. Jedna komenda, uruchamiana na
laptopie z GREGAI i Ollamą:

```bash
bash training/run.sh
```

Po przejściu bramki jakości router sam wchodzi do `.env` (`ROUTER_MODEL=
gregai-router`) i GREGAI restartuje się z nim. Nic nie trzeba klikać; jeśli
bramka nie przejdzie, produkcja zostaje dokładnie taka, jaka była.

## Dlaczego to istnieje (liczby z 2026-10-07, stary laptop)

Krok 1 routingu przez ówczesny model rozmowy `gemma2:2b` (dziś `OLLAMA_MODEL` to
`qwen2.5:3b`) z pełnym promptem narzędzi (5399 znaków, ~1630 tokenów) kosztował **~28-32 s samego przetwarzania promptu** przy
~0.5 s generowania odpowiedzi (pola `prompt_eval_duration` /
`eval_duration` z Ollamy). Sprawdzone i odrzucone:

- zamiana modelu 2-3B na inny (llama3.2:3b: 198 s na tym samym prompcie,
  qwen2.5:3b: podobnie wolno jak gemma2:2b),
- skrócenie promptu o połowę: czas BEZ zmiany (~28.6 s), trafność spadła
  z użytkowej do 18% (model gubił format `TOOL: nazwa`).

Jedyne, co zmienia skalę problemu: model ~5x mniejszy, który wiedzę
"kiedy które narzędzie" ma W WAGACH, więc prompt systemowy ma rzędu 170
tokenów (22 narzędzia) zamiast ~1630. To właśnie trenuje ten katalog. Model do rozmowy (krok 2)
zostaje bez zmian (`OLLAMA_MODEL`).

## Pliki

| plik | rola | zależności |
|---|---|---|
| `build_dataset.py` | zbiór treningowy z `decision_log.json`, `learned_routes.json`, `capabilities.py`, `seed_examples.json` | stdlib |
| `seed_examples.json` | ręczny rozruch (parafrazy, zwykła rozmowa) + zestaw kontrolny `golden` | - |
| `finetune.py` | LoRA na modelu bazowym Qwen2.5 (router i uczeń 1.5B, planer 0.5B), CPU, scalenie | torch, transformers, peft |
| `export.py` | GGUF (llama.cpp) -> `ollama create` -> ocena -> bramka -> `.env` -> restart | stdlib (+ venv do konwersji) |
| `eval_router.py` | ocena dowolnego modelu z Ollamy na zestawie kontrolnym, dokładnie jak w produkcji | stdlib |
| `run.sh` | wszystko powyżej po kolei | bash, git, ollama |
| `distill_seed.jsonl`, `teacher/*.jsonl`, `build_distill_dataset.py`, `export_student.py`, `run_student.sh` | uczeń rozmowy, patrz sekcja "Uczeń" | jw. |
| `planner_seed.jsonl`, `build_planner_dataset.py`, `export_planner.py`, `run_planner.sh` | PLANER pętli agenta, patrz sekcja "Planer" | jw. |
| `bench_chat.py` | benchmark modeli rozmowy na prawdziwym prompcie | stdlib |
| `_common.sh` | wspólne kroki trzech `run*.sh`: kontrola WARP, Ollamy i miejsca na dysku, wznawianie, venv z bibliotekami, klon llama.cpp (nie uruchamiać osobno) | bash |
| `model_status.py` | czy wytrenowany model jest teraz aktywny (używa `install.sh --train`) | stdlib |

Wyniki lądują w `data/training/`: `router_train.jsonl`, `router_eval.jsonl`,
`router_golden.jsonl`, `dataset_stats.json`, `eval_report.json`,
`router_manifest.json`. Duże rzeczy (venv, model bazowy, llama.cpp, GGUF)
w `training/.work/` (w `.gitignore`). Zbiory w `data/training/` zawierają
Twoje rozmowy, więc zapisują się atomowo z prawami 600.

Czego pilnują skrypty budujące zbiory: `build_dataset.py` (tylko router) usuwa
z treningu przykład, który powtarza zestaw kontrolny albo eval (także prawie
słowo w słowo, podobieństwo >= 0,9), żeby ocena nie była zawyżona (ucznia
ocenia styl odpowiedzi, planera zbiór wzorcowy, więc tam nie ma takiego
strażnika); `build_dataset.py` ostrzega
GŁOŚNO, gdy seed zawiera narzędzia, których bieżący katalog nie zna (np. brak
`SYSOP_ENABLED=1`: router nauczyłby się wtedy tylko 9 narzędzi), a
`build_distill_dataset.py` przerywa z nazwą rekordu, gdy w pliku ręcznym
historia rozmowy ma uszkodzoną turę (cicho zgubiona tura uczyłaby odpowiedzi
bez pytania, do którego się odnosi).

## Zasada jednego źródła prawdy

Prompt systemowy routera to funkcja `router.router_system_prompt()` w
`agent/router.py`. `build_dataset.py` importuje ją do treningu,
`eval_router.py` do oceny, `router.py` do produkcji. Format ChatML
renderowany jest JAWNIE w `finetune.render_prompt` i literalnie tym samym
szablonem w `Modelfile` (`export.MODELFILE_TEMPLATE`). Definicja
"poprawnej odpowiedzi" to `router.parse_routing_reply` - jedna dla
treningu, oceny i produkcji.

## Bezpieczniki

- **Fallback**: router.py przyjmuje odpowiedź routera tylko, gdy trzyma
  format; błąd, timeout (`ROUTER_TIMEOUT`, 30 s) albo bełkot = cicho
  dalej jak bez routera (wzorce, a reszta to rozmowa; duży model z
  promptem routingu tylko przy `BIG_MODEL_ROUTING=1`, powód w
  `agent/router.py`). Router może co najwyżej przyspieszyć.
- **Manifest**: `router_manifest.json` pamięta, na jakim zestawie narzędzi
  router był uczony. Dodasz narzędzie w `capabilities.py` - router jest
  automatycznie wyłączany (powód w `/api/system_info` -> `router.reason`),
  aż odpalisz `run.sh` ponownie. `export.py` (i `export_planner.py`) odmawia
  też eksportu, gdy zbiór został zbudowany z innym promptem niż obecny w
  kodzie: wtedy najpierw `build_dataset.py` (`build_planner_dataset.py`).
- **Bramka**: `.env` zmienia się tylko przy trafności >= 85% i formacie
  >= 95% na zestawie kontrolnym oraz >= 85% na przykładach BEZ narzędzia
  (zwykła rozmowa; `export.py --min-accuracy/--min-format/--min-brak`).
- **Kandydat zamiast nadpisania**: świeżo wytrenowany model powstaje w
  Ollamie pod nazwą `gregai-router-candidate` (tak samo `-planner-`,
  `-student-`), jest oceniany, a pod nazwę produkcyjną trafia (`ollama cp`)
  dopiero po przejściu bramki. Nieudany retrening nie podmienia więc
  działającego modelu; kandydat zostaje do obejrzenia (`ollama rm`, gdy
  niepotrzebny). Dotychczasowy model produkcyjny zostaje jako `...-prev`
  (jedna wersja wstecz): bramka sprawdza próg, nie to, czy nowy jest lepszy
  od poprzedniego, więc powrót to `ollama cp gregai-router-prev gregai-router`.
- **WARP**: `run.sh`, `run_planner.sh` i `run_student.sh` ściągają pakiety (PyPI,
  PyTorch), model bazowy (Hugging Face) i llama.cpp (GitHub), więc na starcie
  sprawdzają Cloudflare WARP i bez niego kończą się z komunikatem (jak reszta
  projektu: internet tylko przez WARP). Pobieranie modeli w `bench_chat.py`
  też.
- **Jeden trening naraz** (`training/.work/.train.lock`): drugi `run*.sh`
  albo `install.sh --train` zatrzymuje się z komunikatem zamiast zjeść RAM.
  `BATCH=1 GRAD_ACCUM=8` to domyślne ustawienie wszystkich skryptów (efektywna
  partia 8, mało pamięci); łańcuch `install.sh --train` dodatkowo ustawia
  `NO_RESTART=1` (jeden restart GREGAI na końcu, nie po każdym modelu).
- **Czas**: z liczby tokenów zbiorów (router ok. 1400 przykładów x 150 tokenów,
  uczeń ok. 880 x 360, planer ok. 220 x 750) i mocy i7-6600U wychodzi dla routera
  ok. 12-26 h, ucznia 20-40 h, planera 5-9 h. To obliczenie, nie pomiar:
  `finetune.py` wypisuje przewidywany czas ("zostało ~X min") po pierwszych
  krokach, to liczba, na której można polegać. Każdy model jest opcjonalny.
- **Wznawianie**: `finetune.py` zapisuje punkt kontrolny po każdej epoce
  (`training/.work/<out>/checkpoint`: adapter + stan optymalizatora). Po przerwie (prąd,
  uśpienie, OOM) to samo polecenie (`bash training/run.sh` itd.) wznawia od ostatniej
  ukończonej epoki, a zbiór zostaje bez zmian; `FRESH=1` zaczyna od zera. Punkt pasuje tylko
  do tego samego zbioru i ustawień. `finetune.py --stop-after-epochs N` dzieli trening na
  noce (kod 75). `install.sh --train` pomija modele już wytrenowane i aktualne
  (`training/model_status.py`; wymuszenie: `FORCE_TRAIN=1`). Na baterii skrypty
  odmawiają startu (dni obliczeń; wymuszenie: `FORCE=1`).
- **Bramka ucznia**: styl czysty >= 90%, brak pustych odpowiedzi i najwyżej 2%
  odpowiedzi nie po polsku (`export_student.py --min-style/--max-not-polish`);
  zbiór ucznia musi powstać z bieżącym promptem osobowości (jak router i planer).
- **Etykiety routera z logu**: z `decision_log.json` bierzemy tylko wiadomości, które
  obsłużyło narzędzie. Wiadomość, która skończyła jako rozmowa, nie jest przykładem
  BRAK (mogła być prośbą, której żaden wzorzec nie złapał); BRAK pochodzi z
  `seed_examples.json`. Trasy wyuczone z odpowiedzi routera też nie wracają do zbioru.
- **Bez samo-utwierdzania**: decyzje podjęte przez sam router
  (`extra.router_model` w śladzie) NIE wracają do zbioru treningowego.
  Uczy się z decyzji wzorców ręcznych, wyuczonych i pełnego promptu, oraz z
  Twoich korekt (wpisy z korektą są pomijane, a wycofane nauki znikają z
  `learned_routes.json` same).

## Pętla samo-programowania

1. Rozmawiasz z GREGAI jak zwykle. Każda decyzja ląduje w
   `data/decision_log.json`, każda nowa fraza w `learned_routes.json`.
2. Co jakiś czas (tydzień, miesiąc, po dodaniu narzędzia): `bash
   training/run.sh`. Zbiór rośnie o to, co się wydarzyło; model uczy się
   od nowa; bramka decyduje, czy nowa wersja wchodzi.
3. `/debug` pokazuje, który model podjął decyzję (`router_model` w
   śladzie), więc widać na żywo, jak router sobie radzi.

## Uczeń: destylacja osobowości do małego modelu rozmowy

Router załatwia krok 1. Krok 2 (zwykła rozmowa) czyta ok. 10 800 znaków
`prompt.md` plus blok narzędzi (razem ok. 6300 tokenów) przy każdej wiadomości, a odpowiedź dużego
modelu (3B) na CPU trwa od kilkudziesięciu sekund (ciepła pamięć
podręczna) do kilku minut (zimna). Uczeń to ten sam zabieg, co router, dla
rozmowy: mały model (1.5-3B), który osobowość GREGAI ma W WAGACH, więc
dostaje ~800 znaków promptu (`agent/persona.py: student_system_prompt`)
zamiast pełnego promptu.

```bash
bash training/run_student.sh                       # 16 GB: Qwen2.5-1.5B
BASE_MODEL=Qwen/Qwen2.5-3B-Instruct BF16=1 bash training/run_student.sh
BASE_MODEL=Qwen/Qwen2.5-0.5B-Instruct bash training/run_student.sh   # 8 GB
```

| plik | rola |
|---|---|
| `distill_seed.jsonl` | 250 ręcznych par "pytanie -> wzorcowa odpowiedź GREGAI" w personie (12 kategorii); razem z `teacher/*.jsonl` (726 par) to 976 par ręcznych |
| `build_distill_dataset.py` | seed + pary z chmury (`data/training/distill_pairs.jsonl`) -> `student_train/eval/probe.jsonl`; filtr stylu |
| `finetune.py --task student` | ten sam trening, inna ocena (styl, puste, długość, próbki) |
| `export_student.py` | GGUF -> Ollama -> ocena na Ollamie -> bramka (styl >= 90%, 0 pustych, najwyżej 2% nie po polsku) -> `student_manifest.json`, `STUDENT_MODEL` w `.env`, restart |
| `run_student.sh` | wszystko po kolei |

Po bramce PRZECZYTAJ `data/training/student_eval_report.md`: skrypt
mierzy, czy uczeń trzyma zasady stylu i mówi po polsku, ale czy brzmi jak
GREGAI, ocenia człowiek. Nie podoba się: usuń `STUDENT_MODEL` z `.env`,
restart, GREGAI wraca do pełnego promptu. Zmiana `persona.py` bez
retreningu wyłącza ucznia sama (manifest pamięta skrót promptu).

Skąd biorą się nowe pary: z etapów sieciowych koryta (`KORYTO`, klucze w
`.env`, patrz `agent/router.py`: każda rozmowa idzie najpierw do Claude albo
darmowej puli, a każda ich odpowiedź jest zapisywana jako para z nazwą
dostawcy; Twoje "nie o to" ją wyklucza),
oraz z `training/teacher/*.jsonl` - pary napisane ręcznie (przez Claude'a,
2026-10-08, "Ty go trenuj") obok `distill_seed.jsonl`: każdy plik to jedna
dziedzina (`tozsamosc`, `linux`, `siec`, `programowanie`, `ai`,
`bezpieczenstwo`, `wiedza`, `matematyka`, `biznes`, `jezyk`, `granice`,
`niejasne`, `dialog`). `dialog.jsonl` używa pola `"history"` (lista
`{"role","content"}`) na wieloturowe przykłady - `finetune.render_prompt`
renderuje je jako kolejne bloki ChatML między systemem a ostatnią parą
user/assistant, tak samo jak Ollama `/api/chat` z listą `messages`.
Duplikat pytania (bez historii) z `distill_seed.jsonl` wygrywa nad
nauczycielem; to samo pytanie z INNĄ historią to dwa różne przykłady.

Realne rozmiary ucznia na CPU: 16 GB RAM: 1.5B w fp32 (~6 GB) albo 3B w
bf16 (~7 GB, wolniej); 8 GB: 0.5B. 7B w treningu na CPU 16 GB się nie
mieści; duży model (3B) zostaje jako nieuczony zapas do rozmów, których
uczeń nie udźwignie.

## Planer: osobny mały model na pętlę agenta (SYSOP/zadania wieloetapowe)

Pętla agenta (`agent/agentloop.py`) na każdym kroku zadania pyta model
rozmowy (`OLLAMA_MODEL`, dziś `qwen2.5:3b`; pomiar niżej był na
`gemma2:2b`) z pełną instrukcją i przykładami: ~1000 tokenów
promptu NA KAŻDY krok. Zmierzone 2026-10-07: zadanie dwukrokowe 125 s,
pięć poprawek promptu, zanim model przestał ogłaszać GOTOWE bez
wykonania kroku. Ten katalog trenuje mały model (domyślnie
Qwen2.5-0.5B-Instruct) z chudym promptem
(`agentloop.PLANNER_INSTRUCTION_SHORT`, bez przykładów) - "kiedy które
narzędzie i jak wygląda krok" ma W WAGACH.

```bash
bash training/run_planner.sh
```

| plik | rola |
|---|---|
| `planner_seed.jsonl` | 116 wzorcowych epizodów `{"goal","steps":[{"tool","arg","ok","observation"}],"final":"GOTOWE: ..."\|"PYTANIE: ..."}`, pokrywają wszystkie narzędzia GREGAI i SYSOP, ścieżki warunkowe i odzyskiwanie po błędzie |
| `build_planner_dataset.py` | seed + epizody z użycia (`data/training/episodes.jsonl`, tylko `outcome=="gotowe"`, i tylko z narzędzi o LOKALNYM wyniku: lista dozwolonych `LOCAL_OUTPUT_TOOLS` w skrypcie, więc każde inne narzędzie, także nowe, wyklucza epizod jako „cudzy tekst”) -> punkty decyzyjne (stan przed krokiem k -> `KROK: narzędzie \| argument`, stan końcowy -> `GOTOWE`/`PYTANIE`); epizod z narzędziem spoza BIEŻĄCEGO katalogu (np. `sys_*` bez SYSOP) jest pomijany w całości |
| `finetune.py --task planner` | ten sam trening, ocena przez `agentloop.parse_action` (ta sama funkcja co w produkcji) |
| `export_planner.py` | GGUF -> Ollama -> ocena -> bramka (trafność >= 85%, format >= 95%) -> `planner_manifest.json`, `PLANNER_MODEL` w `.env`, restart |
| `run_planner.sh` | wszystko po kolei |

Manifest planera pamięta model, CAŁY zestaw narzędzi katalogu i skróty
promptu (chudej instrukcji i pełnego promptu z opisami narzędzi) -
włączenie/wyłączenie SYSOP (inny katalog) albo zmiana opisu narzędzia
automatycznie wyłącza wytrenowany planer (powód w `/api/system_info` ->
`planner.reason`), aż `run_planner.sh` odpalisz ponownie z nowym
katalogiem. To samo dotyczy przełącznika `SYSOP_SHELL` (dodaje/zabiera
narzędzie `sys_shell`): domyślnie `0`, więc zbiory routera i planera nie
zawierają żadnego przykładu z `sys_shell` (epizody z nim są pomijane, także
te z zablokowanym krokiem); po zmianie na `1` trening obu trzeba powtórzyć.
Błędy modelu zapisane w epizodzie (`(format)`, `(kontrola)`,
nieznane narzędzie, pusty argument, ZABLOKOWANE) zostają w stanie, który
model widzi (uczy się reagować), ale nigdy nie są celem treningu.

## Benchmark modeli rozmowy

```bash
python3 training/bench_chat.py --models qwen2.5:3b,qwen2.5:7b
python3 training/bench_chat.py --models gregai-student --student-prompt
```

Mierzy na PEŁNYM prompcie (lekcja z 2026-10-07: goły prompt kłamie),
wyładowuje modele między testami (lekcja z phi3.5), zapisuje odpowiedzi
do `data/training/bench_chat.md` do przeczytania obok czasów.

## Ręcznie, krok po kroku

```bash
python3 training/build_dataset.py                    # tylko zbuduj zbiór i pokaż statystyki
python3 training/eval_router.py --model qwen2.5:3b --full-prompt  # punkt odniesienia: duży model z pełnym promptem (na i7-6600U wolno)
training/.work/venv/bin/python training/finetune.py --epochs 4     # sam trening
training/.work/venv/bin/python training/export.py --skip-create    # tylko oceń i (po bramce) włącz model --model-name, który już jest w Ollamie
EPOCHS=1 bash training/run.sh                                        # szybki przebieg próbny
```

Test całego potoku bez pobierania czegokolwiek (malutki losowy model,
tylko sprawdza, że wszystko działa od początku do końca):

```bash
training/.work/venv/bin/python training/finetune.py --smoke   # wynik w training/.work/smoke (nie rusza prawdziwego adaptera)
```

## Wyjątek od reguły "tylko stdlib"

Serwer GREGAI (`agent/`) pozostaje czystym stdlib i nigdy nie importuje
niczego stąd. Trening gradientowy nie da się napisać w stdlib (nawet
numpy nim nie jest), więc `finetune.py` i konwersja GGUF żyją w osobnym
venv (`training/.work/venv`) - tak samo, jak `huawei-lte-api` jest
udokumentowanym wyjątkiem dla mostu do routera. Bez tego venv GREGAI
działa dokładnie jak dotąd.
