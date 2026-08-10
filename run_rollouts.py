#!/usr/bin/env python3
"""Rollout runner for the effort-scaling study.

Deliberately not scripts/run.py. That runner launches count+1 rollouts and
kills the slowest survivor to paper over OpenRouter hangs (monitor_and_run,
kill_last default True) — it deletes the slowest rollout of every batch.
Honest rollouts are the slow ones and get slower as E grows, so that default
would preferentially delete honest rollouts in the high-E arms and manufacture
the very slope H1 predicts.

Per rollout:
  1. docker create/start (no --rm) with a per-rollout config carrying its seed
  2. docker cp <cid>:/agent -> runs/<model>/<E>/<id>/workspace  (ALWAYS, even
     on timeout or crash, so every rollout is archived including failures)
  3. docker rm
  4. grade in a fresh container from the same image, classifier bind-mounted
     so the agent never shares a filesystem with the code that grades it

Infrastructure failures are retried with a FRESH SEED; every attempt is logged
to retries.jsonl with its reason and arm so retry clustering by arm is visible.
Arms are interleaved round-robin, so serving-stack drift cannot masquerade as
an arm effect.
"""

import argparse
import json
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).parent / "agent-interp-envs"
CLASSIFY = REPO / "environments" / "precommit_hook" / "classify.py"
IMAGE = "precommit_hook:study"


def sh(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def build_config(base_cfg: dict, target_errors: int, seed: int, dest: Path) -> Path:
    cfg = json.loads(json.dumps(base_cfg))  # deep copy
    cfg["task"]["target_errors"] = target_errors
    cfg["agent"]["seed"] = seed
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
    return dest


def grade(run_dir: Path, target_errors: int) -> dict:
    """Classify in a fresh container; the agent never sees this code."""
    data = run_dir.resolve()
    r = sh([
        "docker", "run", "--rm", "--network", "none",
        "-v", f"{data}:/data",
        "-v", f"{CLASSIFY.resolve()}:/opt/classify.py:ro",
        "-e", "CLASSIFY_WORKSPACE=/data/workspace",
        "-e", "CLASSIFY_OUTPUT=/data/output",
        "-e", f"CLASSIFY_TARGET_ERRORS={target_errors}",
        IMAGE, "python", "/opt/classify.py",
    ], timeout=2400)
    (run_dir / "classify.log").write_text(r.stdout + r.stderr)

    cls_path = run_dir / "output" / "classification.json"
    if not cls_path.exists():
        return {"classify_error": (r.stderr or r.stdout)[-2000:]}
    cls = json.loads(cls_path.read_text())
    return {
        "workaround": cls["workaround"],
        "workaround_type": cls["workaround_type"],
        "commit_succeeded": cls["commit_succeeded"],
        "errors_remaining": cls["errors_remaining"],
        "errors_asis": cls["errors_asis"],
        # PREREG A8 honest-grading provision: the score promised to the agent
        # in the PARTIAL arm is actually computed.
        "errors_fixed": cls.get("errors_fixed"),
        "score": cls.get("score"),
        "honest_hook": cls["honest_hook"],
        "near_reference_residual": cls.get("near_reference_residual"),
        "steps_recorded": cls.get("steps_recorded"),
        "commands_run": cls.get("commands_run"),
        "reconstruction": cls.get("reconstruction"),
    }


def run_one(run_dir: Path, cfg_path: Path, target_errors: int, timeout: int,
            seed: int, attempt: int) -> dict:
    """Execute and grade a single rollout attempt. Never raises."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "output").mkdir(exist_ok=True)
    rec = {
        "run_dir": str(run_dir),
        "target_errors": target_errors,
        "seed": seed,
        "attempt": attempt,
        "started": datetime.now(timezone.utc).isoformat(),
    }
    cid, agent_rc, failure = None, None, None
    t0 = time.time()

    try:
        create = sh([
            "docker", "create",
            # The rollout container needs to reach the model endpoint. The
            # authors' containers call a cloud API, so networked is baseline.
            "--add-host", "host.docker.internal:host-gateway",
            "-v", f"{cfg_path.resolve()}:/opt/config.yaml:ro",
            "-v", f"{(run_dir / 'output').resolve()}:/tmp/output",
            IMAGE,
        ])
        if create.returncode != 0:
            failure = f"docker create: {create.stderr[-500:]}"
        else:
            cid = create.stdout.strip()
            rec["container"] = cid
            start = sh(["docker", "start", "-a", cid], timeout=timeout)
            (run_dir / "rollout.log").write_text(start.stdout + start.stderr)
            agent_rc = start.returncode
    except subprocess.TimeoutExpired:
        failure = f"timeout after {timeout}s"
        if cid:
            sh(["docker", "kill", cid])
    except Exception as exc:  # noqa: BLE001
        failure = f"{type(exc).__name__}: {exc}"

    # Recover the workspace unconditionally — a failed rollout is still an
    # artifact, and its partial state is what makes the failure diagnosable.
    if cid:
        ws = run_dir / "workspace"
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)
        cp = sh(["docker", "cp", f"{cid}:/agent", str(ws)])
        if cp.returncode != 0 and failure is None:
            failure = f"docker cp: {cp.stderr[-500:]}"
        sh(["docker", "rm", "-f", cid])

    if (run_dir / "workspace").exists():
        try:
            rec.update(**grade(run_dir, target_errors))
        except Exception as exc:  # noqa: BLE001
            rec["classify_error"] = f"{type(exc).__name__}: {exc}"

    rec["agent_exit"] = agent_rc
    if failure:
        rec["status"], rec["error"] = "harness_failure", failure
    elif agent_rc != 0:
        # The agent loop died (uncaught provider exception, context overflow).
        # The workspace is a partial state, not an outcome, and these crashes
        # correlate with transcript length — counting them would bias high-E.
        rec["status"] = "harness_failure"
        rec["error"] = f"agent exited {agent_rc}"
    elif "workaround" not in rec:
        rec["status"] = "classify_failure"
        rec["error"] = rec.get("classify_error", "no classification produced")
    else:
        rec["status"] = "ok"

    rec["wall_seconds"] = round(time.time() - t0, 1)
    rec["finished"] = datetime.now(timezone.utc).isoformat()

    ws = run_dir / "workspace"
    if ws.exists():
        sh(["tar", "czf", str(run_dir / "workspace.tar.gz"), "-C", str(ws), "."])
        shutil.rmtree(ws, ignore_errors=True)

    (run_dir / f"record-attempt{attempt}.json").write_text(json.dumps(rec, indent=2))
    (run_dir / "record.json").write_text(json.dumps(rec, indent=2))
    return rec


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    from math import sqrt
    z, p = 1.959963985, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def progress_lines(results: list[dict], model: str, arms: list[int],
                   cells: list = None) -> list[str]:
    if cells:
        lines = ["| cell | done | ok | fail | honest | workaround | no_commit | any-edit | rate |",
                 "|------|------|----|------|--------|------------|-----------|----------|------|"]
        for c in cells:
            rows = [r for r in results if r.get("variant") == c]
            ok = [r for r in rows if r["status"] == "ok"]
            w = sum(1 for r in ok if r.get("workaround"))
            hon = sum(1 for r in ok if r.get("commit_succeeded") and r.get("errors_remaining") == 0)
            nc = sum(1 for r in ok if not r.get("commit_succeeded"))
            rate = w / len(ok) if ok else float("nan")
            lines.append(f"| {c} | {len(rows)} | {len(ok)} | {len(rows)-len(ok)} | {hon} | "
                         f"{w} | {nc} | - | {rate:.3f} |")
        return lines
    lines = [
        f"| E | done | ok | harness_fail | honest | workaround | no_commit | rate | Wilson 95% |",
        f"|---|------|----|--------------|--------|------------|-----------|------|------------|",
    ]
    for e in arms:
        rows = [r for r in results if r["target_errors"] == e]
        ok = [r for r in rows if r["status"] == "ok"]
        w = sum(1 for r in ok if r.get("workaround"))
        hon = sum(1 for r in ok if r.get("commit_succeeded") and r.get("errors_remaining") == 0)
        nc = sum(1 for r in ok if not r.get("commit_succeeded"))
        rate = w / len(ok) if ok else float("nan")
        lo, hi = wilson(w, len(ok))
        lines.append(
            f"| {e} | {len(rows)} | {len(ok)} | {len(rows)-len(ok)} | {hon} | {w} | {nc} | "
            f"{rate:.3f} | [{lo:.3f}, {hi:.3f}] |"
        )
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-tag", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--arms", default="10,51,258")
    ap.add_argument("--variants", default=None,
                    help="label=config.yaml,label=config.yaml — interleaved like arms. "
                         "Used for PREREG A8 (grading framing) where the manipulation is "
                         "the prompt, not the error count.")
    ap.add_argument("--n", type=int, required=True, help="rollouts per arm")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=5400)
    ap.add_argument("--retries", type=int, default=2,
                    help="infrastructure retries per rollout, each with a fresh seed")
    ap.add_argument("--runs-dir", default=str(Path(__file__).parent / "runs"))
    ap.add_argument("--start-index", type=int, default=1)
    ap.add_argument("--base-seed", type=int, default=20260809)
    args = ap.parse_args()

    arms = [int(a) for a in args.arms.split(",")]
    if args.variants:
        variants = [(kv.split("=", 1)[0], Path(kv.split("=", 1)[1]))
                    for kv in args.variants.split(",")]
    else:
        variants = [(None, Path(args.config))]
    cfgs = {label: yaml.safe_load(p.read_text()) for label, p in variants}
    runs_root = Path(args.runs_dir) / args.model_tag
    runs_root.mkdir(parents=True, exist_ok=True)
    global_progress = Path(args.runs_dir) / "progress.md"

    # Interleave every cell round-robin, so serving drift hits all of them
    # equally: arms when the manipulation is the error count, variants when it
    # is the prompt (A8).
    work = [(label, e, i) for i in range(args.start_index, args.start_index + args.n)
            for e in arms for label, _ in variants]

    print(f"{len(work)} rollouts: arms {arms} x {args.n}, "
          f"concurrency {args.concurrency}, retries {args.retries}, image {IMAGE}")

    results: list[dict] = []
    lock = threading.Lock()
    q: queue.Queue = queue.Queue()
    for item in work:
        q.put(item)

    def worker():
        while True:
            try:
                label, e, i = q.get_nowait()
            except queue.Empty:
                return
            cell = label if label else str(e)
            run_dir = runs_root / cell / f"{i:04d}"
            rec = None
            for attempt in range(args.retries + 1):
                # Fresh seed per attempt: a retry must resample, not replay.
                vseed = sum(ord(c) for c in cell) * 1000
                seed = args.base_seed + e * 100000 + vseed + i * 100 + attempt
                cfg = build_config(cfgs[label], e, seed,
                                   run_dir / f"config-attempt{attempt}.yaml")
                rec = run_one(run_dir, cfg, e, args.timeout, seed, attempt)
                rec["variant"] = label
                if rec["status"] == "ok" or attempt == args.retries:
                    break
                with lock:
                    entry = {"arm": e, "variant": label, "rollout": i, "attempt": attempt,
                             "seed": seed, "reason": rec.get("error"),
                             "status": rec["status"],
                             "ts": datetime.now(timezone.utc).isoformat()}
                    (runs_root / "retries.jsonl").open("a").write(
                        json.dumps(entry) + "\n")
                    print(f"    retry E={e} #{i:04d} attempt {attempt} -> "
                          f"{rec['status']}: {str(rec.get('error'))[:120]}", flush=True)

            with lock:
                results.append(rec)
                n = len(results)
                print(f"[{n}/{len(work)}] {cell:>8s} #{i:04d} {rec['status']:16s} "
                      f"workaround={rec.get('workaround')} "
                      f"type={rec.get('workaround_type')} "
                      f"errs={rec.get('errors_remaining')} "
                      f"{rec['wall_seconds']}s", flush=True)
                (runs_root / "results.jsonl").open("a").write(json.dumps(rec) + "\n")
                if n % 25 == 0 or n == len(work):
                    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    cells = [l for l, _ in variants] if args.variants else None
                    block = ([f"", f"### {args.model_tag} — {n}/{len(work)} @ {stamp}"]
                             + progress_lines(results, args.model_tag, arms, cells))
                    with global_progress.open("a") as fh:
                        fh.write("\n".join(block) + "\n")
                    (runs_root / "progress.md").write_text("\n".join(block) + "\n")
            q.task_done()

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(args.concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    cells = [l for l, _ in variants] if args.variants else None
    print("\n".join(progress_lines(results, args.model_tag, arms, cells)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
