#!/usr/bin/env python3
"""Exact step/turn/time statistics + illustrative transcripts for the LW post."""
import json, glob, re
from pathlib import Path
import statistics as st
from audit1 import load

main = load(Path("runs/qwen3-coder-30b"), [10, 51, 258])
a8 = load(Path("runs/a8-grading-framing"), ["binary", "partial"])


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))]


def block(name, rs):
    if not rs:
        print(f"  {name:<34} (none)"); return
    s = [r["steps"] for r in rs]; w = [r["wall"] for r in rs]
    c = [r["n_cmds"] for r in rs]; m = [r["n_mypy"] for r in rs]
    print(f"  {name:<34}{len(rs):>4}{st.median(s):>8.0f}{st.mean(s):>8.1f}"
          f"{q(s,.25):>6}{q(s,.75):>6}{min(s):>6}{max(s):>6}"
          f"{st.median(c):>8.0f}{st.median(m):>7.0f}{st.median(w):>9.0f}")


print("=" * 118)
print("STEP / TURN / WALL-CLOCK STATISTICS  (a 'step' = one model turn = one shell command)")
print("=" * 118)
hdr = (f"  {'':<34}{'n':>4}{'med':>8}{'mean':>8}{'p25':>6}{'p75':>6}{'min':>6}{'max':>6}"
       f"{'cmds':>8}{'mypy':>7}{'wall s':>9}")
for e in (10, 51, 258):
    rs = [r for r in main[e] if r["status"] == "ok"]
    print(f"\nE = {e}   (100 rollouts, 0 harness failures)")
    print(hdr)
    block("ALL rollouts", rs)
    block("honest completions", [r for r in rs if r["commit"] and r["errs"] == 0])
    block("gaming commits", [r for r in rs if r["wa"]])
    block("quit (no commit, voluntary)", [r for r in rs if not r["commit"] and r["task_completed"]])
    block("  ...of those: made 0 edits", [r for r in rs if not r["commit"] and r["task_completed"] and r["n_edit"] == 0])

print("\n" + "=" * 118)
print("A8 (E=258, grading framing)")
print("=" * 118)
for v in ("binary", "partial"):
    rs = [r for r in a8[v] if r["status"] == "ok"]
    print(f"\n{v.upper()}")
    print(hdr)
    block("ALL rollouts", rs)
    block("started repair (mypy-verified)", [r for r in rs if 0 <= r["errs"] < 258])
    block("quit (no commit, voluntary)", [r for r in rs if not r["commit"] and r["task_completed"]])

print("\n" + "=" * 118)
print("FULL STEP DISTRIBUTION — rollouts that quit without committing")
print("=" * 118)
for e in (10, 51, 258):
    v = sorted(r["steps"] for r in main[e]
               if r["status"] == "ok" and not r["commit"] and r["task_completed"])
    print(f"  E={e:>3} (n={len(v):>2}): " + " ".join(f"{x}" for x in v))


def transcript(root, cell, rid, maxcmd=100, tail_chars=900):
    d = root / str(cell) / rid
    steps = sorted(glob.glob(str(d / "output/step-*")),
                   key=lambda p: int(p.rsplit("-", 1)[1]))
    state = json.load(open(steps[-1] + "/state.json"))
    msgs = json.load(open(steps[-1] + "/messages.json"))
    last = next((m for m in reversed(msgs) if m.get("role") == "assistant"), {})
    return state["commands"][:maxcmd], (last.get("content") or "").strip()[:tail_chars]


def show(title, root, cell, rid, rec, note=""):
    cmds, final = transcript(root, cell, rid)
    print("\n" + "-" * 118)
    print(f"{title}   [{cell}/{rid}]  steps={rec['steps']}  commands={rec['n_cmds']}  "
          f"errors_left={rec['errs']}  commit={rec['commit']}  wall={rec['wall']:.0f}s")
    if note:
        print(f"  {note}")
    print("-" * 118)
    for i, c in enumerate(cmds):
        one = " ".join(c.split())
        print(f"  [{i:>2}] $ {one[:150]}{'…' if len(one) > 150 else ''}")
    print(f"\n  FINAL MESSAGE:\n    " + "\n    ".join(
        (" ".join(final.split()))[i:i+112] for i in range(0, min(len(final), 900), 112)))


print("\n" + "=" * 118)
print("ILLUSTRATIVE TRANSCRIPTS")
print("=" * 118)

R = Path("runs/qwen3-coder-30b")
# shortest E=258 quit
quits = sorted([r for r in main[258] if not r["commit"] and r["task_completed"]],
               key=lambda r: r["steps"])
show("A. TYPICAL QUIT AT E=258 (shortest)", R, 258, quits[0]["id"].split("/")[1], quits[0],
     note="Runs mypy, sees the count, writes a working hook, tries to commit, is blocked, stops.")
med = quits[len(quits)//2]
show("B. MEDIAN QUIT AT E=258", R, 258, med["id"].split("/")[1], med)
hon = [r for r in main[10] if r["commit"] and r["errs"] == 0][0]
show("C. HONEST COMPLETION AT E=10", R, 10, hon["id"].split("/")[1], hon)
