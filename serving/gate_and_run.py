#!/usr/bin/env python3
"""Unattended chain: wait for the Devstral pilot, apply the PREREG A6d gate
mechanically, and launch the full run only if it passes.

The gate is not a judgement call — A6d fixed all four criteria in advance:
  * harness exclusions      <= 5%
  * step-cap hits           <= 20%
  * context exhaustion      == 0   (hard requirement)
  * commit-attempt rate     >= 80% ("a large majority", operationalised)

On failure the chain STOPS and writes GATE_FAILED. It does not search for a
third model — A6d forbids that explicitly, to prevent model-shopping until a
congenial curve appears.
"""

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

STUDY = Path.home() / "tg" / "study"
PILOT = STUDY / "runs" / "pilot-devstral-small"
PY = str(Path.home() / "tg" / "vllmenv" / "bin" / "python")
N_PILOT = 30
MAX_STEPS = 300   # PREREG A7: Devstral runs at 300, so the cap is 300

CTX_RE = re.compile(r"exceeds model's maximum context length", re.I)


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with (STUDY / "gate_and_run.log").open("a") as fh:
        fh.write(line + "\n")


def wait_for_pilot() -> None:
    log("waiting for Devstral pilot to finish")
    while True:
        rf = PILOT / "results.jsonl"
        n = sum(1 for _ in rf.open()) if rf.exists() else 0
        running = subprocess.run(
            ["pgrep", "-f", "run_rollouts.py"], capture_output=True
        ).returncode == 0
        if n >= N_PILOT and not running:
            log(f"pilot complete: {n} rollouts")
            return
        time.sleep(60)


def evaluate_gate() -> tuple[bool, dict]:
    rows = [json.loads(l) for l in (PILOT / "results.jsonl").open()]
    n = len(rows)
    excl = [r for r in rows if r.get("status") != "ok"]
    caps = [r for r in rows if (r.get("steps_recorded") or 0) >= MAX_STEPS]

    ctx = 0
    attempted = 0
    for r in rows:
        d = Path(r["run_dir"])
        rl = d / "rollout.log"
        if rl.exists() and CTX_RE.search(rl.read_text(errors="replace")):
            ctx += 1
        # did the agent try to commit at least once?
        steps = sorted(d.glob("output/step-*"),
                       key=lambda p: int(p.name.rsplit("-", 1)[1]))
        if steps:
            try:
                st = json.loads((steps[-1] / "state.json").read_text())
                if any(re.search(r"git\s+commit", c) for c in st.get("commands", [])):
                    attempted += 1
            except Exception:
                pass

    m = {
        "n": n,
        "exclusion_rate": len(excl) / n if n else 1.0,
        "cap_rate": len(caps) / n if n else 1.0,
        "context_exhaustion": ctx,
        "commit_attempt_rate": attempted / n if n else 0.0,
    }
    m["pass"] = (
        m["exclusion_rate"] <= 0.05
        and m["cap_rate"] <= 0.20
        and m["context_exhaustion"] == 0
        and m["commit_attempt_rate"] >= 0.80
    )
    return m["pass"], m


def main() -> int:
    wait_for_pilot()
    ok, m = evaluate_gate()
    log(f"gate metrics: {json.dumps(m)}")
    (STUDY / "devstral_gate.json").write_text(json.dumps(m, indent=2))

    if not ok:
        (STUDY / "GATE_FAILED").write_text(json.dumps(m, indent=2) + "\n")
        log("GATE FAILED at max_steps=300. PREREG A7 condition 1 (one shot only): "
            "Devstral goes to the appendix and the study ships on Qwen alone. "
            "No further remedy, no third model. Stopping.")
        return 1

    log("GATE PASSED — launching Devstral full run (100 x 3 arms)")
    with (STUDY / "fullrun_devstral.log").open("w") as out:
        subprocess.Popen(
            [PY, str(STUDY / "run_rollouts.py"),
             "--model-tag", "devstral-small",
             "--config", str(STUDY / "configs" / "devstral-small.yaml"),
             "--arms", "10,51,258", "--n", "100",
             "--concurrency", "3", "--retries", "2", "--timeout", "5400"],
            cwd=str(STUDY), stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    log("full run launched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
