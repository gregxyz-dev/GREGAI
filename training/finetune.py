"""
training/finetune.py

LoRA fine-tuning małego modelu-routera (domyślnie Qwen/Qwen2.5-1.5B-Instruct, decyzja
2026-10-11; planer 0.5B ustawia run_planner.sh)
na zbiorze z training/build_dataset.py, na CPU. To JEDYNY plik w projekcie,
który potrzebuje bibliotek ML (torch, transformers, peft) - żyje w osobnym
venv (training/.work/venv, patrz run.sh) i NIGDY nie jest importowany przez
serwer GREGAI (agent/*), który zostaje przy czystym stdlib.

Dlaczego mały model (pierwotnie 0.5B, od 2026-10-11 1.5B), a nie produkcyjny gemma2:2b: router odpowiada jednym z ~10
tokenów-decyzji, nie prowadzi rozmowy - to zadanie klasyfikacji z lekką
ekstrakcją argumentu. Zmierzone 2026-10-07 na laptopie użytkownika: koszt
kroku 1 to w ~98% PRZETWARZANIE promptu, nie generowanie. Model 5x mniejszy
na prompcie wielokrotnie krótszym (rzędu 170 tokenów przy 22 narzędziach zamiast ~1630) to realny skok z
~30s do pojedynczych sekund - tam, gdzie zmiana promptu i zamiana modelu
2-3B na inny nic nie dały.

Format rozmowy renderowany TU jawnie (ChatML Qwen2.5), nie przez
tokenizer.apply_chat_template: ten sam literalny szablon jest w Modelfile
(training/export.py), więc to, co model widzi w treningu, jest bajt w bajt
tym, co Ollama wyśle mu w produkcji. Strata liczona TYLKO na tokenach
odpowiedzi asystenta (prompt ma -100).

Użycie (patrz run.sh):
  python finetune.py --base Qwen/Qwen2.5-1.5B-Instruct --out training/.work/out
  python finetune.py --smoke            # pipeline na malutkim losowym modelu
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from env_loader import load_env  # noqa: E402

load_env()  # jak w pozostałych skryptach: zestaw narzędzi (SYSOP_ENABLED) i modele z .env

DATA_DIR = ROOT / "data" / "training"

IM_START, IM_END, EOT = "<|im_start|>", "<|im_end|>", "<|endoftext|>"


def render_prompt(system: str, user: str, history: list[dict] | None = None) -> str:
    """Identyczne z TEMPLATE w Modelfile (export.py). Zmieniasz tu =
    zmieniasz tam, inaczej model dostanie w produkcji inny prompt niż w
    treningu.

    `history` (uczeń rozmowy): poprzednie tury jako kolejne bloki ChatML
    user/assistant między systemem a bieżącym pytaniem. Tak samo renderuje
    to Ollama dla /api/chat z historią przy szablonie bez .Messages
    (tryb "legacy": każda para user+assistant to osobne wykonanie
    szablonu, system tylko w pierwszym, ostatni blok ucięty na .Response),
    czyli dokładnie to, co router._ollama_chat wysyła uczniowi w produkcji."""
    parts = [f"{IM_START}system\n{system}{IM_END}\n"]
    for turn in history or []:
        role = "assistant" if turn.get("role") == "assistant" else "user"
        parts.append(f"{IM_START}{role}\n{turn.get('content', '')}{IM_END}\n")
    parts.append(f"{IM_START}user\n{user}{IM_END}\n{IM_START}assistant\n")
    return "".join(parts)


def render_answer(assistant: str) -> str:
    return f"{assistant}{IM_END}\n"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_tiny_base(out_dir: Path, train_records: list[dict]) -> Path:
    """Tryb --smoke: malutki LOSOWY model architektury Qwen2 + tokenizer
    BPE wytrenowany na własnym zbiorze. Nie umie nic - służy wyłącznie do
    sprawdzenia, że cały potok (tokenizacja, maska strat, LoRA, pętla,
    eval, merge, zapis, odczyt) działa od początku do końca bez
    pobierania czegokolwiek z internetu."""
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers, decoders
    from transformers import PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM
    import torch

    out_dir.mkdir(parents=True, exist_ok=True)
    tok = Tokenizer(models.BPE(unk_token=EOT))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(vocab_size=1500, special_tokens=[EOT, IM_START, IM_END],
                                  initial_alphabet=pre_tokenizers.ByteLevel.alphabet())
    corpus = [render_prompt(r["system"], r["user"], r.get("history")) + render_answer(r["assistant"]) for r in train_records]
    tok.train_from_iterator(corpus, trainer=trainer)
    fast = PreTrainedTokenizerFast(tokenizer_object=tok, eos_token=IM_END, pad_token=EOT,
                                   additional_special_tokens=[IM_START, IM_END])
    fast.save_pretrained(out_dir)
    torch.manual_seed(0)
    cfg = Qwen2Config(vocab_size=len(fast), hidden_size=64, intermediate_size=128, num_hidden_layers=2,
                      num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=512,
                      tie_word_embeddings=True, eos_token_id=fast.eos_token_id, pad_token_id=fast.pad_token_id)
    Qwen2ForCausalLM(cfg).save_pretrained(out_dir, safe_serialization=True)
    return out_dir


class Encoded:
    __slots__ = ("input_ids", "labels")

    def __init__(self, input_ids, labels):
        self.input_ids, self.labels = input_ids, labels


def encode(tokenizer, record: dict, max_len: int) -> Encoded | None:
    # Prompt i odpowiedź tokenizowane OSOBNO i sklejane: dokładnie tak
    # zobaczy to Ollama w produkcji (tokenizuje sam prompt, potem
    # generuje), a maska strat jest wtedy trywialnie dokładna.
    prompt_ids = tokenizer(render_prompt(record["system"], record["user"], record.get("history")), add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer(render_answer(record["assistant"]), add_special_tokens=False)["input_ids"]
    if len(prompt_ids) + len(answer_ids) > max_len:
        return None
    return Encoded(prompt_ids + answer_ids, [-100] * len(prompt_ids) + answer_ids)


def collate(batch: list[Encoded], pad_id: int):
    import torch
    width = max(len(b.input_ids) for b in batch)
    ids = torch.full((len(batch), width), pad_id, dtype=torch.long)
    labels = torch.full((len(batch), width), -100, dtype=torch.long)
    attn = torch.zeros((len(batch), width), dtype=torch.long)
    for i, b in enumerate(batch):
        n = len(b.input_ids)
        ids[i, :n] = torch.tensor(b.input_ids)
        labels[i, :n] = torch.tensor(b.labels)
        attn[i, :n] = 1
    return ids, attn, labels


def generate_decision(model, tokenizer, system: str, user: str, max_new_tokens: int = 40) -> str:
    import torch
    ids = tokenizer(render_prompt(system, user), add_special_tokens=False, return_tensors="pt")
    eos_ids = [tokenizer.convert_tokens_to_ids(IM_END)]
    if tokenizer.eos_token_id is not None:
        eos_ids.append(tokenizer.eos_token_id)
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=max_new_tokens, do_sample=False,
                             eos_token_id=eos_ids, pad_token_id=tokenizer.pad_token_id)
    text = tokenizer.decode(out[0, ids["input_ids"].shape[1]:], skip_special_tokens=True)
    return text.split("\n")[0].strip()


def generate_reply(model, tokenizer, system: str, user: str, max_new_tokens: int = 200,
                   history: list[dict] | None = None) -> str:
    """Pełna odpowiedź (wiele linii) dla ucznia rozmowy, w odróżnieniu od
    generate_decision, które czyta tylko pierwszą linię (router)."""
    import torch
    ids = tokenizer(render_prompt(system, user, history), add_special_tokens=False, return_tensors="pt")
    eos_ids = [tokenizer.convert_tokens_to_ids(IM_END)]
    if tokenizer.eos_token_id is not None:
        eos_ids.append(tokenizer.eos_token_id)
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=max_new_tokens, do_sample=False,
                             eos_token_id=eos_ids, pad_token_id=tokenizer.pad_token_id)
    return tokenizer.decode(out[0, ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def evaluate_student(model, tokenizer, records: list[dict], limit: int | None = None) -> dict:
    """Ocena ucznia rozmowy: nie ma jednej poprawnej odpowiedzi, więc
    mierzymy to, co da się zmierzyć (styl wg agent/persona.py, puste
    odpowiedzi, długość) i pokazujemy próbki do przeczytania."""
    import persona
    sample = records[:limit] if limit else records
    rows = []
    for r in sample:
        got = generate_reply(model, tokenizer, r["system"], r["user"], history=r.get("history"))
        rows.append({"user": r["user"], "expected": r["assistant"], "got": got, "style_problems": persona.violates_style(got),
                     "with_history": bool(r.get("history"))})
    n = max(1, len(rows))
    return {
        "n": len(rows),
        "style_ok": sum(1 for x in rows if not x["style_problems"] and x["got"]) / n,
        "empty": sum(1 for x in rows if not x["got"]),
        "avg_chars": round(sum(len(x["got"]) for x in rows) / n),
        "samples": rows[:5],
        "rows": rows,
    }


def evaluate_planner(model, tokenizer, records: list[dict], limit: int | None = None) -> dict:
    """Planer pętli agenta: ta sama definicja poprawności co produkcja
    (agentloop.parse_action). Trafność = ten sam rodzaj (KROK/GOTOWE/
    PYTANIE) i, dla KROK, to samo narzędzie; argument osobno (dokładnie,
    bez wielkości liter). Treść GOTOWE/PYTANIE nie jest porównywana
    słowo w słowo, bo ma wiele poprawnych wersji."""
    import agentloop
    sample = records[:limit] if limit else records
    fmt_ok = ok = arg_ok = arg_total = 0
    errors = []
    for r in sample:
        expected = agentloop.parse_action(r["assistant"])
        got_text = generate_decision(model, tokenizer, r["system"], r["user"], max_new_tokens=80)
        got = agentloop.parse_action(got_text)
        if got is not None:
            fmt_ok += 1
        hit = got is not None and expected is not None and got[0] == expected[0] and (got[0] != "KROK" or got[1] == expected[1])
        if hit:
            ok += 1
            if expected[0] == "KROK" and expected[2]:
                arg_total += 1
                if got[2].strip().lower() == expected[2].strip().lower():
                    arg_ok += 1
        else:
            errors.append({"goal": r.get("goal"), "expected": r["assistant"], "got": got_text})
    n = max(1, len(sample))
    return {"n": len(sample), "accuracy": ok / n, "format_ok": fmt_ok / n,
            "arg_exact": (arg_ok / arg_total) if arg_total else None, "errors": errors[:30]}


def evaluate_generation(model, tokenizer, records: list[dict], limit: int | None = None) -> dict:
    """Ta sama definicja poprawności co produkcja: router.parse_routing_reply."""
    import router as router_mod
    sample = records[:limit] if limit else records
    ok = fmt_ok = arg_ok = arg_total = 0
    errors = []
    for r in sample:
        expected = router_mod.parse_routing_reply(r["assistant"])
        got_text = generate_decision(model, tokenizer, r["system"], r["user"])
        got = router_mod.parse_routing_reply(got_text)
        if got is not None:
            fmt_ok += 1
        if got is not None and expected is not None and got[0] == expected[0]:
            ok += 1
            if expected[1]:
                arg_total += 1
                if (got[1] or "").strip().lower() == expected[1].strip().lower():
                    arg_ok += 1
        else:
            errors.append({"user": r["user"], "expected": r["assistant"], "got": got_text})
    n = max(1, len(sample))
    return {
        "n": len(sample), "accuracy": ok / n, "format_ok": fmt_ok / n,
        "arg_exact": (arg_ok / arg_total) if arg_total else None, "errors": errors[:30],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="Qwen/Qwen2.5-1.5B-Instruct", help="model bazowy (HF id albo katalog)")
    ap.add_argument("--train", default=str(DATA_DIR / "router_train.jsonl"))
    ap.add_argument("--eval", default=str(DATA_DIR / "router_eval.jsonl"))
    ap.add_argument("--out", default=None, help="katalog wyniku (domyślnie training/.work/out; z --smoke: training/.work/smoke, "
                                                "żeby próba potoku nie nadpisała prawdziwego adaptera)")
    ap.add_argument("--epochs", type=float, default=None, help="liczba epok (domyślnie 3, z --smoke 1)")
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    # 384: sam prompt routera (22 narzędzia) to ok. 170 tokenów, a przykład z długim
    # argumentem (remember, research_web) potrzebuje jeszcze kilkudziesięciu na treść
    # i odpowiedź. Przy 256 znikały po cichu właśnie najdłuższe przykłady.
    ap.add_argument("--max-len", type=int, default=384)
    ap.add_argument("--threads", type=int, default=0, help="0 = wszystkie rdzenie")
    ap.add_argument("--dtype", choices=["fp32", "bf16"], default="fp32",
                    help="fp32: pewne i szybsze na starszych CPU; bf16: 2x mniej RAM (uczeń 3B na 16 GB), wolniej bez AVX512")
    ap.add_argument("--limit", type=int, default=0, help="użyj tylko N pierwszych przykładów (testy)")
    ap.add_argument("--eval-limit", type=int, default=0, help="generatywna ocena na N przykładach eval (0 = wszystkie)")
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--smoke", action="store_true", help="malutki losowy model, 48 przykładów, test potoku")
    ap.add_argument("--fresh", action="store_true",
                    help="zignoruj punkt kontrolny z poprzedniego, przerwanego treningu i zacznij od zera")
    ap.add_argument("--stop-after-epochs", type=int, default=0,
                    help="po tylu epokach tej sesji zapisz punkt kontrolny i zakończ (kod 75); kolejne uruchomienie "
                         "wznowi od niego (podział treningu na noce)")
    ap.add_argument("--task", choices=["router", "student", "planner"], default="router",
                    help="router: ocena trafności TOOL/BRAK; student: ocena stylu odpowiedzi (persona.violates_style); "
                         "planner: ocena linii KROK/GOTOWE/PYTANIE (agentloop.parse_action)")
    args = ap.parse_args()
    if args.epochs is None:
        args.epochs = 1.0 if args.smoke else 3.0

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import LoraConfig, get_peft_model, get_peft_model_state_dict, set_peft_model_state_dict
    except ImportError as e:
        # 1.32.2 (audyt tura 7): zamiast surowego śladu błędu - co zrobić.
        sys.exit(f"Brak bibliotek treningu ({e.name}). Uruchom: bash training/run.sh "
                 "(tworzy osobne środowisko training/.work/venv z torch, transformers i peft).")

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    torch.set_num_threads(args.threads or (os.cpu_count() or 2))

    out_dir = Path(args.out or ROOT / "training" / ".work" / ("smoke" if args.smoke else "out"))
    out_dir.mkdir(parents=True, exist_ok=True)
    if not Path(args.train).exists():
        raise SystemExit(f"Brak zbioru treningowego {args.train} - najpierw build_dataset.py / build_distill_dataset.py / build_planner_dataset.py")
    train_records = read_jsonl(Path(args.train))
    eval_records = read_jsonl(Path(args.eval)) if Path(args.eval).exists() else []

    if args.smoke:
        args.base = str(make_tiny_base(out_dir.parent / "tiny_base", train_records))
        args.limit, args.eval_limit = 48, 8
        print(f"[smoke] malutki losowy model w {args.base}")
    if args.limit:
        train_records = train_records[:args.limit]

    print(f"Baza: {args.base}")
    print(f"Trening: {len(train_records)} przykładów, eval: {len(eval_records)}, epoki: {args.epochs}, "
          f"LoRA r={args.rank} alpha={args.alpha}, batch {args.batch} x accum {args.grad_accum}, "
          f"wątki: {torch.get_num_threads()}")

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = EOT if EOT in tokenizer.get_vocab() else tokenizer.eos_token

    # Najpierw dane, potem model: pusty zbiór (albo same przykłady dłuższe niż
    # --max-len) kończy się tu komunikatem, a nie po wczytaniu modelu i nie
    # pętlą bez końca w treningu.
    encoded = [e for e in (encode(tokenizer, r, args.max_len) for r in train_records) if e is not None]
    dropped = len(train_records) - len(encoded)
    if dropped:
        print(f"Pominięto {dropped} przykładów dłuższych niż --max-len {args.max_len}")
    if not encoded:
        why = (f"plik {args.train} jest pusty" if not train_records
               else f"żaden z {len(train_records)} przykładów z {args.train} nie mieści się w --max-len {args.max_len}")
        raise SystemExit(f"Brak przykładów do treningu: {why}. Najpierw zbuduj zbiór (build_dataset.py / "
                         "build_distill_dataset.py / build_planner_dataset.py).")
    eval_encoded = [e for e in (encode(tokenizer, r, args.max_len) for r in eval_records) if e is not None]

    dtype = torch.bfloat16 if args.dtype == "bf16" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(args.base, dtype=dtype)
    model.config.use_cache = False

    lora = LoraConfig(r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout, bias="none",
                      task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Parametry trenowane: {trainable:,} z {total:,} ({100 * trainable / total:.2f}%)")

    steps_per_epoch = math.ceil(len(encoded) / (args.batch * args.grad_accum))
    total_steps = max(1, int(steps_per_epoch * args.epochs))
    warmup = max(1, int(0.06 * total_steps))
    optim = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.0)

    def lr_at(step: int) -> float:
        if step < warmup:
            return args.lr * (step + 1) / warmup
        progress = (step - warmup) / max(1, total_steps - warmup)
        return args.lr * max(0.05, 1.0 - progress)

    def eval_loss() -> float | None:
        if not eval_encoded:
            return None
        model.eval()
        losses = []
        with torch.no_grad():
            for i in range(0, len(eval_encoded), args.batch):
                ids, attn, labels = collate(eval_encoded[i:i + args.batch], tokenizer.pad_token_id)
                losses.append(model(input_ids=ids, attention_mask=attn, labels=labels).loss.item())
        model.train()
        return sum(losses) / len(losses)

    print(f"Kroków optymalizatora: {total_steps} ({steps_per_epoch}/epokę), warmup {warmup}")
    history = []
    model.train()
    step = 0
    t0 = time.monotonic()
    epoch = 0
    done = False

    # Punkt kontrolny po każdej epoce (adapter + stan optymalizatora): trening trwa godziny
    # do dób, a przerwa prądu, uśpienie albo OOM kasowały całą pracę. Pasuje tylko do tego
    # samego zbioru i tych samych ustawień (podpis), inaczej jest ignorowany.
    ckpt_dir = out_dir / "checkpoint"
    signature = hashlib.sha1(json.dumps({
        "base": args.base, "task": args.task, "rank": args.rank, "alpha": args.alpha, "lr": args.lr, "dropout": args.dropout,
        "batch": args.batch, "grad_accum": args.grad_accum, "epochs": args.epochs, "max_len": args.max_len, "seed": args.seed,
        "dtype": args.dtype, "n": len(encoded),
        "data": hashlib.sha1(Path(args.train).read_bytes()).hexdigest() if not args.smoke else "smoke",
    }, sort_keys=True).encode("utf-8")).hexdigest()
    resumed_from = 0
    # Zapis punktu kontrolnego podmienia katalogi w dwóch krokach (stary -> checkpoint.old, nowy ->
    # checkpoint). Przerwanie między nimi zostawia tylko checkpoint.old: wracamy do niego.
    old_dir = out_dir / "checkpoint.old"
    if not args.fresh and not ckpt_dir.exists() and (old_dir / "state.json").exists():
        os.replace(old_dir, ckpt_dir)
        print("Odzyskuję poprzedni punkt kontrolny (zapis nowego został przerwany w trakcie podmiany).")
    if args.fresh:
        shutil.rmtree(ckpt_dir, ignore_errors=True)
        shutil.rmtree(old_dir, ignore_errors=True)
    elif (ckpt_dir / "state.json").exists():
        # Kopia świeżego adaptera: gdy wczytanie punktu zawiedzie w połowie (adapter wczytany, optymalizator
        # nie), wracamy do niej, żeby "od zera" naprawdę było od zera, a nie od połowicznie wytrenowanego adaptera.
        pristine = {k: v.detach().clone() for k, v in get_peft_model_state_dict(model).items()}
        try:
            state = json.loads((ckpt_dir / "state.json").read_text(encoding="utf-8"))
            if state.get("signature") != signature:
                print("Punkt kontrolny pochodzi z innego zbioru albo innych ustawień: ignoruję go i zaczynam od zera.")
                shutil.rmtree(ckpt_dir, ignore_errors=True)
            else:
                from safetensors.torch import load_file
                set_peft_model_state_dict(model, load_file(str(ckpt_dir / "adapter" / "adapter_model.safetensors")))
                optim.load_state_dict(torch.load(ckpt_dir / "optimizer.pt", map_location="cpu", weights_only=True))
                epoch, step, history = int(state["epoch"]), int(state["step"]), list(state["history"])
                resumed_from = epoch
                done = step >= total_steps
                print(f"Wznawiam od punktu kontrolnego: ukończone epoki {epoch}, krok {step}/{total_steps}.")
        except Exception as e:
            print(f"Nie udało się wczytać punktu kontrolnego ({type(e).__name__}: {e}): zaczynam od zera.")
            set_peft_model_state_dict(model, pristine)
            shutil.rmtree(ckpt_dir, ignore_errors=True)
            epoch, step, history, done, resumed_from = 0, 0, [], False, 0
    t_step0, step0 = time.monotonic(), step

    def save_checkpoint() -> None:
        tmp = out_dir / "checkpoint.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        model.save_pretrained(tmp / "adapter")
        torch.save(optim.state_dict(), tmp / "optimizer.pt")
        (tmp / "state.json").write_text(json.dumps({"signature": signature, "epoch": epoch, "step": step, "history": history},
                                                   ensure_ascii=False), encoding="utf-8")
        old = out_dir / "checkpoint.old"
        shutil.rmtree(old, ignore_errors=True)
        if ckpt_dir.exists():
            os.replace(ckpt_dir, old)
        os.replace(tmp, ckpt_dir)
        shutil.rmtree(old, ignore_errors=True)

    while not done:
        epoch += 1
        random.seed(args.seed + epoch)
        random.shuffle(encoded)
        running = []
        micro = 0
        for i in range(0, len(encoded), args.batch):
            ids, attn, labels = collate(encoded[i:i + args.batch], tokenizer.pad_token_id)
            loss = model(input_ids=ids, attention_mask=attn, labels=labels).loss / args.grad_accum
            loss.backward()
            running.append(loss.item() * args.grad_accum)
            micro += 1
            if micro % args.grad_accum == 0 or i + args.batch >= len(encoded):
                for g in optim.param_groups:
                    g["lr"] = lr_at(step)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optim.step()
                optim.zero_grad(set_to_none=True)
                step += 1
                if step % 10 == 0 or step == total_steps:
                    elapsed = time.monotonic() - t0
                    eta = (time.monotonic() - t_step0) / max(1, step - step0) * (total_steps - step)
                    print(f"  krok {step}/{total_steps}  strata {sum(running[-10 * args.grad_accum:]) / len(running[-10 * args.grad_accum:]):.4f}"
                          f"  lr {lr_at(step):.2e}  {elapsed / 60:.1f} min, zostało ~{eta / 60:.1f} min", flush=True)
                if step >= total_steps:
                    done = True
                    break
        ev = eval_loss()
        history.append({"epoch": epoch, "train_loss": sum(running) / max(1, len(running)), "eval_loss": ev})
        print(f"Epoka {epoch}: strata treningowa {history[-1]['train_loss']:.4f}, eval {ev if ev is None else round(ev, 4)}")
        try:
            save_checkpoint()
        except Exception as e:  # brak miejsca itp.: trening idzie dalej, tylko bez możliwości wznowienia
            print(f"UWAGA: nie zapisano punktu kontrolnego ({type(e).__name__}: {e})")
        if args.stop_after_epochs and epoch - resumed_from >= args.stop_after_epochs and not done:
            print(f"Zatrzymano po {args.stop_after_epochs} epokach tej sesji. Uruchom to samo polecenie ponownie, żeby wznowić.")
            return 75

    model.eval()
    if args.task == "student":
        gen = evaluate_student(model, tokenizer, eval_records, args.eval_limit or None) if eval_records else None
        if gen:
            print(f"Ocena ucznia (eval, n={gen['n']}): styl czysty {gen['style_ok']:.1%}, puste {gen['empty']}, "
                  f"śr. {gen['avg_chars']} znaków; przykłady:")
            for e in gen["samples"]:
                print(f"    > {e['user']!r}\n      {e['got']!r}")
    elif args.task == "planner":
        gen = evaluate_planner(model, tokenizer, eval_records, args.eval_limit or None) if eval_records else None
    else:
        gen = evaluate_generation(model, tokenizer, eval_records, args.eval_limit or None) if eval_records else None
    if gen and args.task in ("router", "planner"):
        arg_txt = "-" if gen["arg_exact"] is None else f"{gen['arg_exact']:.1%}"
        print(f"Ocena generatywna (eval, n={gen['n']}): trafność {gen['accuracy']:.1%}, format {gen['format_ok']:.1%}, "
              f"argument dokładnie {arg_txt}")
        for e in gen["errors"][:10]:
            print(f"    x {(e.get('user') or e.get('goal'))!r}: oczekiwano {e['expected']!r}, dostano {e['got']!r}")

    adapter_dir, merged_dir = out_dir / "adapter", out_dir / "merged"
    model.save_pretrained(adapter_dir)
    merged = model.merge_and_unload()
    merged.config.use_cache = True
    merged.save_pretrained(merged_dir, safe_serialization=True)
    tokenizer.save_pretrained(merged_dir)

    # Kontrola: scalony model wczytany Z DYSKU odpowiada tak samo jak
    # ten w pamięci (to on pójdzie do GGUF, nie obiekt w RAM).
    # Najpierw odpowiedź modelu z pamięci, potem zwolnienie go (i optymalizatora):
    # dwie pełne kopie naraz mogłyby zabić proces z braku RAM na końcu wielogodzinnego
    # treningu, już po zapisaniu wag.
    probe = eval_records[0] if eval_records else train_records[0]
    a = generate_decision(model, tokenizer, probe["system"], probe["user"])
    model = merged = optim = None  # zwolnienie referencji (del kłóci się z domknięciami wyżej)
    gc.collect()
    reloaded = AutoModelForCausalLM.from_pretrained(merged_dir, dtype=dtype)
    b = generate_decision(reloaded, tokenizer, probe["system"], probe["user"])
    print(f"Kontrola scalenia: w pamięci {a!r} / z dysku {b!r} -> {'OK' if a == b else 'ROZNICA'}")

    report = {
        "base": args.base, "train_examples": len(encoded), "eval_examples": len(eval_encoded),
        "epochs": args.epochs, "steps": step, "lora": {"r": args.rank, "alpha": args.alpha},
        "task": args.task, "history": history, "generation_eval": gen, "merge_consistent": a == b,
        "minutes": round((time.monotonic() - t0) / 60, 1), "smoke": args.smoke,
        "render_prompt_example": render_prompt("SYSTEM", "USER"),
    }
    (out_dir / "train_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Adapter: {adapter_dir}\nScalony model: {merged_dir}\nRaport: {out_dir / 'train_report.json'}")
    if a == b:
        shutil.rmtree(ckpt_dir, ignore_errors=True)  # trening skończony: punkt kontrolny już niepotrzebny
        return 0
    # Różnica: punkt kontrolny zostaje (adapter i scalony model są na dysku), żeby ponowne
    # uruchomienie nie zaczynało treningu od zera; bramka w export*.py i tak oceni scalony model.
    print("UWAGA: kontrola scalenia wykryła różnicę; punkt kontrolny zostawiam (patrz train_report.json).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
