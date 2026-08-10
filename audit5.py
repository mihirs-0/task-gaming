#!/usr/bin/env python3
"""Audit 5: excerpts (Q8), partial-credit belief (Q13), A8 terminal check, confounds (Q21)."""
import json, glob, re, sys
from pathlib import Path
from audit1 import load

E_ARMS = [10, 51, 258]
main = load(Path("runs/qwen3-coder-30b"), E_ARMS)
a8 = load(Path("runs/a8-grading-framing"), ["binary", "partial"])

COUNT_REF = re.compile(r"\b(258|51|\d{2,3})\s+(type\s+)?errors?\b|\berrors?\b[^.]{0,20}\b(258|51)\b", re.I)
SCOPE = re.compile(r"beyond the scope|out of scope|separate (issue|concern)|not (?:part of|within) "
                   r"the (?:scope|task)|rather than fix|infrastructure for type checking", re.I)
CREDIT = re.compile(r"partial credit|proportional|score|credit|worth (?:it|trying)|"
                    r"even if no commit|graded", re.I)

print("="*100)
print("Q8 — MODEL REFERENCES THE ERROR COUNT, THEN REFRAMES/ABANDONS")
print("="*100)
shown = 0
for e in [51, 258]:
    for r in main[e]:
        if r["commit"] or not r["final"]:
            continue
        t = " ".join(r["final"].split())
        if COUNT_REF.search(t) and SCOPE.search(t) and shown < 6:
            m = SCOPE.search(t)
            s = max(0, m.start()-260)
            print(f"\n[{r['id']} | {r['steps']} steps | {r['n_edit']} edits | errs={r['errs']}]")
            print(f"  ...{t[s:m.end()+140]}...")
            shown += 1

print("\n" + "="*100)
print("Q8b — COUNTEREXAMPLES: saw a large count and still did substantial repair")
print("="*100)
for e in [51, 258]:
    cands = sorted([r for r in main[e] if r["errs"] is not None and r["errs"] < e],
                   key=lambda r: r["errs"])[:3]
    for r in cands:
        print(f"\n[{r['id']} | {r['steps']} steps | {r['n_edit']} edits | "
              f"fixed {e-r['errs']}/{e} | commit={r['commit']} type={r['wtype']}]")
        print(f"  {' '.join((r['final'] or '(no final text)').split())[:300]}")

print("\n" + "="*100)
print("Q13 — DID THE MODEL REPRESENT THE PARTIAL-CREDIT STATEMENT?")
print("="*100)
for v in ("binary", "partial"):
    rs = [r for r in a8[v] if r["status"] == "ok"]
    hits = [r for r in rs if CREDIT.search(r["final"] or "")]
    strong = [r for r in rs if re.search(r"partial credit|proportional|even if no commit",
                                         r["final"] or "", re.I)]
    print(f"  {v:<8} final-message mentions credit/score/graded: {len(hits)}/{len(rs)} "
          f"({len(hits)/len(rs)*100:.0f}%);  explicit 'partial credit'/'proportional': "
          f"{len(strong)}/{len(rs)} ({len(strong)/len(rs)*100:.0f}%)")

print("\n  Examples (PARTIAL arm, explicit references):")
n = 0
for r in a8["partial"]:
    if n >= 4: break
    t = " ".join((r["final"] or "").split())
    m = re.search(r"partial credit|proportional|even if no commit", t, re.I)
    if m:
        s = max(0, m.start()-200)
        print(f"\n  [{r['id']} | {r['n_edit']} edits | fixed {258-r['errs']}]")
        print(f"    ...{t[s:m.end()+220]}...")
        n += 1
print("\n  Examples (BINARY arm, any credit reference):")
n = 0
for r in a8["binary"]:
    if n >= 2: break
    t = " ".join((r["final"] or "").split())
    m = CREDIT.search(t)
    if m:
        s = max(0, m.start()-160)
        print(f"\n  [{r['id']} | {r['n_edit']} edits]")
        print(f"    ...{t[s:m.end()+180]}...")
        n += 1

print("\n" + "="*100)
print("A8 TERMINAL CHECK — what are the 'other_failure' (no commit, not voluntary) rollouts?")
print("="*100)
for v in ("binary", "partial"):
    rs = [r for r in a8[v] if r["status"]=="ok" and not r["commit"] and not r["task_completed"]]
    caps = sum(1 for r in rs if r["steps"] >= 100)
    ctx = sum(1 for r in rs if r["ctx_exhausted"])
    print(f"  {v:<8} n={len(rs):>3}  hit step cap={caps}  context exhausted={ctx}  "
          f"other={len(rs)-caps-ctx}  median steps={sorted(r['steps'] for r in rs)[len(rs)//2] if rs else 0}")

print("\n" + "="*100)
print("Q21 — CONFOUND SCAN: config parity across the three main arms")
print("="*100)
import yaml
cfgs = {}
for e in E_ARMS:
    f = sorted(glob.glob(f"runs/qwen3-coder-30b/{e}/*/config-attempt0.yaml"))
    if not f:
        f = sorted(glob.glob(f"runs/qwen3-coder-30b/_configs/E{e}.yaml"))
    cfgs[e] = yaml.safe_load(open(f[0])) if f else None
if all(cfgs.values()):
    ref = cfgs[E_ARMS[0]]
    for e in E_ARMS[1:]:
        c = cfgs[e]
        diffs = []
        for k in ("system_prompt", "user_prompt"):
            if c["prompts"][k] != ref["prompts"][k]:
                diffs.append(f"prompts.{k}")
        for k in set(ref["agent"]) | set(c["agent"]):
            if k == "seed": continue
            if ref["agent"].get(k) != c["agent"].get(k):
                diffs.append(f"agent.{k}: {ref['agent'].get(k)} vs {c['agent'].get(k)}")
        for k in set(ref["task"]) | set(c["task"]):
            if k == "target_errors": continue
            if ref["task"].get(k) != c["task"].get(k):
                diffs.append(f"task.{k}")
        print(f"  E={E_ARMS[0]} vs E={e}: "
              + ("IDENTICAL except target_errors/seed" if not diffs else f"DIFFERS: {diffs}"))
    print(f"  prompt user_prompt length (chars): "
          + ", ".join(f"E={e}: {len(cfgs[e]['prompts']['user_prompt'])}" for e in E_ARMS))
    print("  -> prompt text does NOT mention the error count, so prompt tokens are constant.")
else:
    print("  configs not found locally")

print("\n  Seed scheme (base 20260809 + E*1e5 + id*100 + attempt) — distinct per arm by construction.")
for e in E_ARMS:
    seeds = sorted({r["seed"] for r in main[e] if r["seed"]})
    print(f"    E={e:>3}: {len(seeds)} distinct seeds, min={min(seeds)}, max={max(seeds)}")
