# Regex w praktyce
type: Wiedza

Część [[Programowanie]]. Wyrażenia regularne opisują wzorce w tekście: szukanie, walidacja, wyciąganie fragmentów, podmiana. Są potężne, ale trudne w utrzymaniu; do prostych rzeczy wystarczą metody napisów (`in`, `startswith`, `split`, `replace`). Składnia różni się lekko między silnikami (Python `re`, JavaScript, `grep -E`, `grep -P`, `sed -E`); różnice zaznaczono.

## Składnia podstawowa

- `.` dowolny znak (bez nowej linii), `\d` cyfra, `\w` znak słowa (litera, cyfra, `_`), `\s` biały znak. Duże litery to negacja: `\D`, `\W`, `\S`.
- `[abc]` jeden z znaków, `[a-z]` zakres, `[^abc]` żaden z nich.
- Kotwice: `^` początek, `$` koniec, `\b` granica słowa.
- Kwantyfikatory: `*` zero lub więcej, `+` jeden lub więcej, `?` zero lub jeden, `{3}` dokładnie 3, `{2,5}` od 2 do 5, `{2,}` co najmniej 2.
- Alternatywa: `kot|pies`. Grupa: `(ab)+`. Grupa nieprzechwytująca: `(?:ab)+`.
- Znaki specjalne dosłownie: `\.`, `\*`, `\(`, `\[`, `\\`, `\$`.
- Zachłanność: `.*` bierze jak najwięcej; `.*?` jak najmniej (leniwie). Dla `<b>a</b><b>b</b>` wzorzec `<b>.*</b>` zwróci całość, a `<b>.*?</b>` pojedyncze tagi.

## Python: moduł re

```python
import re

re.search(r"\d+", "abc 123 x")         # pierwsze dopasowanie gdziekolwiek
re.match(r"\d+", "123 x")              # dopasowanie od początku napisu
re.fullmatch(r"\d{4}-\d{2}-\d{2}", "2026-10-22")   # cały napis
re.findall(r"\d+", "a1 b22 c333")      # ['1', '22', '333']
re.sub(r"\s+", " ", "a   b \n c")      # 'a b c'
re.split(r"[,;]\s*", "a, b;c")         # ['a', 'b', 'c']
wzor = re.compile(r"(?P<rok>\d{4})-(?P<mc>\d{2})")
m = wzor.search("data 2026-10")
if m:
    print(m.group("rok"), m["mc"], m.start(), m.end())
```

- Zawsze pisz wzorce jako surowe napisy `r"..."`, inaczej `\d` i `\b` zostaną źle zinterpretowane przez Pythona (`"\b"` to backspace).
- `search`, `match` i `fullmatch` zwracają obiekt dopasowania albo `None`; sprawdzaj przed użyciem.
- `findall`: bez grup zwraca listę napisów; z jedną grupą listę zawartości grupy; z wieloma grupami listę krotek. Dla pełnych obiektów: `finditer`.
- Grupy numerowane: `m.group(1)`, `m.groups()`. Nazwane: `(?P<nazwa>...)` (w Pythonie składnia z `P`; sama `(?<nazwa>...)` działa w JS, nie w `re`).
- Podmiana z grupami: `re.sub(r"(\d+)-(\d+)", r"\2-\1", tekst)`; z funkcją: `re.sub(r"\d+", lambda m: str(int(m.group()) * 2), tekst)`.
- Flagi: `re.IGNORECASE` (`re.I`), `re.MULTILINE` (`re.M`, `^` i `$` na każdej linii), `re.DOTALL` (`re.S`, `.` łapie też nową linię), `re.VERBOSE` (`re.X`, spacje i komentarze we wzorcu).
- Skompilowany wzorzec (`re.compile`) opłaca się przy wielokrotnym użyciu (choć `re` też buforuje wzorce wewnętrznie).
- W Pythonie 3 `\w` i `\d` domyślnie obejmują Unicode, więc `\w` pasuje do polskich liter (ą, ł, ż). W JS `\w` nigdy nie obejmuje polskich liter (nawet z flagą `u`); użyj `\p{L}` z flagą `u`, np. `/[\p{L}\d_]+/u`.

## Przykłady praktyczne

- Liczba całkowita (ze znakiem): `[+-]?\d+`
- Liczba dziesiętna z kropką lub przecinkiem: `\d+(?:[.,]\d+)?`
- Data ISO: `\d{4}-\d{2}-\d{2}` (tylko format; nie sprawdza, czy data istnieje, do tego `datetime.date.fromisoformat`).
- Prosty adres e-mail do wstępnego filtra: `[\w.+-]+@[\w-]+(?:\.[\w-]+)+` (pełna walidacja e-mail regexem jest niepraktyczna; potwierdź adres wysyłając wiadomość).
- Adres IPv4 (kształt): `\b(?:\d{1,3}\.){3}\d{1,3}\b` (nie sprawdza zakresu 0-255).
- Zawartość cudzysłowów: `"([^"]*)"` (negowana klasa jest szybsza i pewniejsza niż `".*?"`).

## Lookaround (asercje)

Dopasowują kontekst bez jego zużywania.

- `(?=...)` za mną jest, `(?!...)` za mną nie ma.
- `(?<=...)` przede mną jest, `(?<!...)` przede mną nie ma. W Pythonie (`re`) wzorzec w lookbehind musi mieć stałą długość; JavaScript i .NET dopuszczają dowolną długość, inne silniki różnie.
- Przykład: liczba poprzedzona `$`: `(?<=\$)\d+`. Słowo nie poprzedzone "nie ": `(?<!nie )dobry`.
- Silnik `grep -E` (ERE) ich nie ma; `grep -P` (GNU, perlowy) ma.

## grep i sed w terminalu

- `grep -E "wzor" plik` - rozszerzone regexy (`+`, `?`, `|`, `()` bez backslasha). Bez `-E` w podstawowych (BRE) trzeba pisać `\+`, `\|`.
- `grep -o -E "[0-9]+" plik` - tylko dopasowane fragmenty. `-i` ignoruj wielkość liter, `-n` numery linii, `-r` rekurencyjnie, `-v` odwróć, `-w` całe słowa.
- `grep -P` - składnia perlowa (`\d`, lookaround, leniwe kwantyfikatory); dostępne w GNU grep na Ubuntu. `\d` w zwykłym `grep -E` nie jest gwarantowane, użyj `[0-9]` lub `[[:digit:]]`.
- `sed -E 's/([0-9]+)-([0-9]+)/\2-\1/' plik` - podmiana z grupami; flaga `g` na końcu zamienia wszystkie wystąpienia w linii. `-i` edytuje plik w miejscu (zrób kopię: `-i.bak`).
- Więcej poleceń: [[Komendy Linuksa: pliki i tekst]], skrypty: [[Bash: skrypty]].
- W Bashu `[[ $s =~ ^[0-9]+$ ]]` używa ERE; grupy w tablicy `BASH_REMATCH`.

## JavaScript

```js
const re = /(\d{4})-(\d{2})/g;
"2026-10 i 2027-01".match(re);                  // ["2026-10", "2027-01"]
const m = /(?<rok>\d{4})-(?<mc>\d{2})/.exec("2026-10");
m.groups.rok;                                   // "2026"
for (const x of "a1 b22".matchAll(/\d+/g)) console.log(x[0]);
"a  b".replace(/\s+/g, " ");
```

- Bez flagi `g` `replace` zamienia tylko pierwsze wystąpienie. `matchAll` wymaga `g`.
- Wzorzec z flagą `g` używany wielokrotnie przez `.test()` lub `.exec()` zachowuje `lastIndex` i może dawać zaskakujące wyniki; twórz nowy obiekt lub resetuj `lastIndex = 0`.
- `\p{L}` (litera Unicode) działa z flagą `u`: `/\p{L}+/u`.
- Dynamiczny wzorzec z tekstu użytkownika: najpierw ucieknij znaki specjalne; w Pythonie `re.escape(tekst)`. W JS od ES2025 jest `RegExp.escape(tekst)` (Chrome 136+, Firefox 134+, Safari 18.2+); dla starszych przeglądarek: `s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")`.

## Pułapki

- **Nadmierne cofanie (catastrophic backtracking, ReDoS):** zagnieżdżone kwantyfikatory typu `(a+)+b` lub `(.*)*` na długim, niepasującym tekście potrafią zawiesić program na bardzo długo. Nie przepuszczaj cudzych wzorców ani nieograniczonych tekstów przez ryzykowne regexy (patrz [[Bezpieczeństwo aplikacji webowych]]). Ogranicz długość wejścia, upraszczaj wzorce, używaj klas negowanych.
- `.` nie pasuje do nowej linii bez `DOTALL`; `^`/`$` bez `MULTILINE` oznaczają początek/koniec całego napisu (`$` pasuje też tuż przed końcowym `\n`).
- `re.match` kotwiczy tylko początek, nie koniec: do walidacji użyj `fullmatch` lub `^...$`.
- Nie parsuj HTML ani zagnieżdżonych struktur regexem: użyj parsera (`html.parser`, `json`, `ast`).
- Nie waliduj regexem wszystkiego (e-mail, URL, daty): użyj dedykowanych narzędzi (`urllib.parse`, `datetime`, `ipaddress`).

## Jak testować wzorce

Zbierz przykłady pasujące i niepasujące (także brzegowe: pusty tekst, polskie znaki), sprawdź w terminalu (`python3 -c "import re; print(re.findall(r'\d+', '1 a 22'))"`) i wstaw do testów ([[Debugowanie i testowanie]]).
