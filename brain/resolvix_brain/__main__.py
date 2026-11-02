"""CLI: ``python -m resolvix_brain compile|chat|eval|bench`` (see README)."""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import statistics
import sys
import time
from datetime import datetime

from resolvix_contracts.models import CallChannel, CallContext, KBSource, TurnRequest

from .kb import KBCompileError, load_entries
from .settings import BrainSettings

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _settings(args) -> BrainSettings:
    s = BrainSettings.from_env()
    over = {}
    if getattr(args, "mock", False):
        over["llm_mode"] = "mock"
    if getattr(args, "lexical", False):
        over["embed_mode"] = "lexical"
    return dataclasses.replace(s, **over) if over else s


def _source(spec: str | None, s: BrainSettings) -> KBSource:
    if not spec:
        return s.default_kb_source()
    if spec.startswith(("http://", "https://")):
        return KBSource(kind="url", location=spec)
    return KBSource(kind="file", location=spec.removeprefix("file:"))


# ------------------------------------------------------------------ compile
def cmd_compile(args) -> int:
    from .brain import ResolvixBrain

    s = _settings(args)

    async def go():
        b = ResolvixBrain(s)
        try:
            info = await b.reload_kb(_source(args.source, s))
        finally:
            await b.aclose()
        return info

    try:
        info = asyncio.run(go())
    except KBCompileError as exc:
        print("KB COMPILE FAILED:", file=sys.stderr)
        for p in exc.problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(info.model_dump_json(indent=2))
    for w in info.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 0


# ------------------------------------------------------------------ chat
def cmd_chat(args) -> int:
    from .brain import ResolvixBrain

    s = _settings(args)

    async def go() -> None:
        b = ResolvixBrain(s)
        plan = await b.start_call(CallContext(call_id=args.call_id, channel=CallChannel.test,
                                              caller_number=args.number, started_at=datetime.now(s.tz)))
        print(f"[brain] llm_mode={s.llm_mode} kb={plan.kb_version} embedder={b.embedder.name} health={b.health()['status']}")
        print("AGENT>", plan.greeting_text)
        idx = 0
        while True:
            try:
                text = input("YOU> ")
            except (EOFError, KeyboardInterrupt):
                break
            if text.strip() in ("/quit", "/exit"):
                break
            idx += 1
            req = TurnRequest(call_id=args.call_id, turn_index=idx, user_text=text, received_at=datetime.now(s.tz),
                              dtmf="0" if text.strip() == "/0" else None)
            spoken = []
            async for ev in b.handle_turn(req):
                print(ev.model_dump_json())
                if ev.type == "speech":
                    spoken.append(ev.text)
            print("AGENT>", " ".join(spoken) or "(no speech)")
        await b.end_call(args.call_id)
        await b.aclose()

    asyncio.run(go())
    return 0


# ------------------------------------------------------------------ eval
def cmd_eval(args) -> int:
    import tempfile
    from pathlib import Path

    from .evaluation import EVAL_DIR, run_eval
    from .settings import BRAIN_DIR

    s, set_dir, which = _settings(args), None, args.set
    with tempfile.TemporaryDirectory() as tmp:
        if args.kb_set == "akgec-draft":
            # Evaluate the DRAFT AKGEC knowledge base (brain/data/kb.jsonl) with its own question sets (eval/akgec/).
            # The Brain only serves approved entries, so a temporary copy marked approved is built for this run only;
            # brain/data/kb.jsonl is never modified, nothing is approved or published.
            src = BRAIN_DIR / "data" / "kb.jsonl"
            rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
            for r in rows:
                r["status"] = "approved"
            copy = Path(tmp) / "kb_eval_only.jsonl"
            copy.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
            s = dataclasses.replace(s, kb_source=f"file:{copy}")
            set_dir = EVAL_DIR / "akgec"
            if which == "all":
                which = "answerable,abstain"        # the other sets do not depend on the KB: run them without --kb-set
            print("NOTE: evaluating the DRAFT AKGEC KB (temporary approved copy, evaluation only; staff have approved nothing)")
        sc = asyncio.run(run_eval(s, which, set_dir))
    print(json.dumps(sc.to_json(), indent=2) if args.json else sc.render())
    return sc.exit_code()


# ------------------------------------------------------------------ bench
def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] if xs else 0.0


def cmd_bench(args) -> int:
    from .brain import ResolvixBrain
    from .evaluation import NOW, Driver, load_jsonl
    from .safety import Lexicon
    from .rules import RuleTable

    s = _settings(args)
    out: dict[str, object] = {"llm_mode": s.llm_mode}

    async def go():
        t = time.perf_counter()
        b = ResolvixBrain(s)
        await b.ready()
        out["startup_embedder_and_kb_ms"] = round((time.perf_counter() - t) * 1000)
        out["embedder"] = b.embedder.name
        out["kb_tokens"] = b.store.active.kb.info.token_count
        lex = Lexicon.from_rules_file(s.urgency_rules_file)
        phrases = [r["text"] for r in load_jsonl("safety")] * 50
        t = time.perf_counter()
        for p in phrases:
            lex.safety_hit(p)
        out["safety_lexicon_us_per_call"] = round((time.perf_counter() - t) / len(phrases) * 1e6, 1)
        rt = RuleTable.from_file(s.urgency_rules_file)
        t = time.perf_counter()
        for _ in range(20000):
            rt.evaluate({"event_type": "exam", "minutes_to_event": 15, "blocked": True})
        out["rule_eval_us_per_call"] = round((time.perf_counter() - t) / 20000 * 1e6, 2)
        qs = [r["text"] for r in load_jsonl("answerable")]
        emb = []
        for q in qs * 2:
            t = time.perf_counter()
            await asyncio.to_thread(b.embedder.embed_queries, [q])
            emb.append((time.perf_counter() - t) * 1000)
        out["embed_query_ms_p50_p95"] = [round(_pct(emb, 0.5), 1), round(_pct(emb, 0.95), 1)]
        faq, llm = [], []
        for i, q in enumerate(qs):
            ev = await Driver(b, f"bench-{i}").say(q)
            sm = ev[-1].summary
            (faq if sm.path == "faq" else llm).append(sm.latency_ms.get("brain_total", 0))
        out["turn_ms_faq_path_p50_p95"] = [round(_pct(faq, 0.5), 1), round(_pct(faq, 0.95), 1), len(faq)] if faq else None
        out["turn_ms_other_path_p50_p95"] = [round(_pct(llm, 0.5), 1), round(_pct(llm, 0.95), 1), len(llm)] if llm else None
        # concurrency: N simultaneous short calls
        n = args.concurrency

        async def call(i):
            t0 = time.perf_counter()
            await Driver(b, f"bc-{i}").say("hostel gate timing")
            return (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        lat = await asyncio.gather(*[call(i) for i in range(n)])
        out[f"concurrent_{n}_calls"] = {"wall_ms": round((time.perf_counter() - t0) * 1000),
                                       "per_call_p50_p95_ms": [round(_pct(list(lat), 0.5)), round(_pct(list(lat), 0.95))]}
        if s.llm_mode == "live":
            out["live_llm"] = await _bench_live(b, s)
        else:
            out["live_llm"] = "NOT RUN (LLM_MODE=mock or no GROQ_API_KEY): prompt-caching and time-to-first-token are unmeasured"
        await b.aclose()

    asyncio.run(go())
    print(json.dumps(out, indent=2))
    return 0


async def _bench_live(b, s: BrainSettings) -> dict:
    """Spike S2: identical prefix twice per model; record cached_tokens, ttft, total (cold vs warm)."""
    prefix = b.store.active.kb.prefix
    res: dict[str, list] = {}
    for model in (s.llm_model, s.llm_fallback_model):
        rows = []
        for attempt in ("cold", "warm"):
            msgs = [{"role": "system", "content": prefix}, {"role": "system", "content": "CURRENT CONTEXT\nNow: bench"},
                    {"role": "user", "content": "What time does the hostel gate close?"}]
            try:
                r = await b.llm_client.complete(msgs, model=model, max_tokens=s.llm_max_tokens, temperature=s.llm_temperature,
                                                reasoning_effort=s.llm_reasoning_effort, ttft_timeout=10, total_timeout=20)
                rows.append({"call": attempt, "ttft_ms": r.ttft_ms, "total_ms": r.total_ms, "prompt_tokens": r.prompt_tokens,
                             "cached_tokens": r.cached_tokens})
            except Exception as exc:
                rows.append({"call": attempt, "error": type(exc).__name__})
        res[model] = rows
    return res


# ------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="resolvix_brain", description="Resolvix Brain CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mock", action="store_true", help="force LLM_MODE=mock")
    common.add_argument("--lexical", action="store_true", help="force the offline lexical embedder (degraded)")

    c = sub.add_parser("compile", parents=[common], help="compile a KB and print KBVersionInfo + warnings")
    c.add_argument("--source", help="path or http(s) URL; default is KB_SOURCE")
    c.set_defaults(fn=cmd_compile)

    ch = sub.add_parser("chat", parents=[common], help="interactive REPL; prints each event as JSON plus the spoken text")
    ch.add_argument("--lang", default="hi")
    ch.add_argument("--call-id", default="cli-call")
    ch.add_argument("--number", default="+919000000001", help="caller number (use '' for none)")
    ch.set_defaults(fn=cmd_chat)

    e = sub.add_parser("eval", parents=[common], help="run the eval sets and print a scorecard")
    e.add_argument("--set", default="all", help="all | comma list of answerable,abstain,urgency,safety,human,robustness")
    e.add_argument("--json", action="store_true")
    e.add_argument("--kb-set", choices=["sample", "akgec-draft"], default="sample",
                   help="sample = contracts/kb/sample_kb.jsonl with eval/*.jsonl (default); akgec-draft = data/kb.jsonl (drafts) with eval/akgec/*.jsonl")
    e.set_defaults(fn=cmd_eval)

    b = sub.add_parser("bench", parents=[common], help="latency / cache benchmark (Spike S2 when LLM_MODE=live)")
    b.add_argument("--concurrency", type=int, default=50)
    b.set_defaults(fn=cmd_bench)

    args = p.parse_args(argv)
    if getattr(args, "number", None) == "":
        args.number = None
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
