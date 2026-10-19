#!/usr/bin/env python3
"""Per-thread CPU/state sampler for the League game process (read-only).

Why: to tell whether the low in-game FPS comes from the game's own threads being
CPU-pegged (contention on the 4-thread CPU) or from them blocking at the
Metal -> GL hand-off wait (present path). The decisive signal is, at low FPS,
whether the game's main/render threads sit near 100% (state R) or mostly sleep
(state S).

This only reads scheduling metadata:

  /proc/<pid>/task/<tid>/stat   -> per-thread state and utime/stime
  /proc/<pid>/task/<tid>/comm   -> thread name (the Indium overlay names its threads, so the
                                   hot threads can be attributed instead of guessed: indium-submit,
                                   indium-poll, indium-batch, indium-retire)

It never reads or writes the game's memory, never injects anything and never
sends a signal. It is deliberately inert with respect to the anti-cheat; see
docs/VANGUARD.md for the read-only rule.

Usage:
    python3 tools/game-thread-probe.py
    python3 tools/game-thread-probe.py --pid 1234 --interval 2 --out /tmp/game-threads.log

It finds the game on its own by scanning /proc for the Darling host process
(`mldr`) whose argv names the game bundle. Stop it by creating the stop file
(default /tmp/opencode/stop-probe) or with Ctrl-C.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import time

GAME_COMMS = ("LeagueofLegends", "League of Legends")
# Two traps when matching the game: Darling runs it through its Mach-O loader
# (`mldr`), and the kernel truncates comm to 15 characters, so the task name is
# at best `LeagueofLegend`; the bundle on disk is `LeagueOfLegends.app` (capital
# O) while its executable is `LeagueofLegends`. Compare case-insensitively and
# accept the truncated comm prefix.
GAME_COMM_PREFIX = "leagueoflegend"
GAME_EXE_MARKERS = ("leagueoflegends.app/contents/macos/leagueoflegends",)


def _read(path: str, *, binary: bool = False):
    try:
        with open(path, "rb" if binary else "r", encoding=None if binary else "utf-8",
                  errors=None if binary else "replace") as fh:
            return fh.read()
    except OSError:
        return None


def find_game_pid(wanted: int | None = None) -> int | None:
    """Return the pid of the game host process, or None.

    Keys off the task name first, then argv (read-only; nothing is printed from
    it), so this does not depend on the loader's process name.
    """
    if wanted is not None:
        return wanted
    own = os.getpid()
    for entry in sorted(os.listdir("/proc"), key=lambda s: int(s) if s.isdigit() else -1):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == own:
            continue
        comm = _read(f"/proc/{pid}/comm")
        if comm is not None and comm.strip().lower().startswith(GAME_COMM_PREFIX):
            return pid
        raw = _read(f"/proc/{pid}/cmdline", binary=True)
        if not raw:
            continue
        try:
            argv = raw.decode("utf-8", "replace").split("\0")
        except Exception:
            continue
        for arg in argv:
            if any(marker in arg.lower() for marker in GAME_EXE_MARKERS):
                return pid
    return None


def parse_stat(text: str) -> tuple[str, int, int] | None:
    """Return (state, utime, stime) from a /proc/<pid>/stat line.

    The comm field can contain spaces and parentheses, so parse from the last
    ')' to be safe.
    """
    close = text.rfind(")")
    if close < 0:
        return None
    rest = text[close + 2:].split()
    # After comm: state is field 3, so index 0 here; utime/stime are fields
    # 14/15, i.e. indices 11 and 12 of the remainder.
    try:
        state = rest[0]
        utime = int(rest[11])
        stime = int(rest[12])
    except (IndexError, ValueError):
        return None
    return state, utime, stime


def sample(pid: int, prev: dict[int, tuple[int, int]]) -> tuple[list[tuple[int, str, str, float]], int, int]:
    """Sample all threads of pid. Returns (rows, running_count, thread_count)."""
    ticks = os.sysconf("SC_CLK_TCK")
    rows: list[tuple[int, str, str, float]] = []
    running = 0
    count = 0

    task_dir = f"/proc/{pid}/task"
    try:
        tids = [t for t in os.listdir(task_dir) if t.isdigit()]
    except OSError:
        return rows, running, count

    for tid_s in tids:
        tid = int(tid_s)
        text = _read(f"{task_dir}/{tid_s}/stat")
        if text is None:
            continue
        parsed = parse_stat(text)
        if parsed is None:
            continue
        state, utime, stime = parsed
        count += 1
        if state == "R":
            running += 1
        total = utime + stime
        old = prev.get(tid)
        prev[tid] = (utime, stime)
        if old is not None:
            delta = total - (old[0] + old[1])
            used = delta / ticks  # seconds of CPU used during this interval (the loop turns it into a core share)
        else:
            used = 0.0
        # Thread name: the Indium overlay sets it (Darling forwards pthread_setname_np to the host's
        # prctl(PR_SET_NAME)), so report it next to the tid. Linux truncates it to 15 characters.
        name = (_read(f"{task_dir}/{tid_s}/comm") or "").strip()
        rows.append((tid, name, state, used))

    rows.sort(key=lambda r: r[3], reverse=True)
    return rows, running, count


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, default=None, help="game pid; auto-detected when omitted")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between samples (default 2)")
    ap.add_argument("--out", default="/tmp/opencode/game-threads.log", help="log file")
    ap.add_argument("--stop-file", default="/tmp/opencode/stop-probe", help="stop when this file exists")
    ap.add_argument("--trace", default="~/.darling/private/tmp/metal-trace.log",
                    help="optional metal-debug-waits trace to tail")
    args = ap.parse_args(argv)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    trace_path = os.path.expanduser(args.trace)

    pid = args.pid
    prev: dict[int, tuple[int, int]] = {}
    waited = False
    last_sample = 0.0
    while pid is None or not os.path.isdir(f"/proc/{pid}"):
        if not waited:
            print("waiting for the game process (comm 'LeagueofLegends')...", flush=True)
            waited = True
        if os.path.exists(args.stop_file):
            print("stop file present before a game started; exiting", flush=True)
            return 0
        time.sleep(1.0)
        pid = find_game_pid(args.pid)
        prev.clear()

    with open(args.out, "a", encoding="utf-8") as out:
        out.write(f"# probe attached to pid={pid} at {_dt.datetime.now().isoformat(timespec='seconds')}\n")
        out.flush()
        trace_pos = 0
        while os.path.isdir(f"/proc/{pid}"):
            if os.path.exists(args.stop_file):
                break
            time.sleep(args.interval)
            rows, running, count = sample(pid, prev)
            # sample() reports seconds of CPU per thread; divide by the real elapsed time so the printed numbers are a
            # share of one core regardless of --interval (they used to be scaled by the interval).
            now = time.monotonic()
            elapsed = (now - last_sample) if last_sample else 0.0
            last_sample = now
            share = (100.0 / elapsed) if elapsed > 0 else 0.0
            stamp = _dt.datetime.now().strftime("%H:%M:%S")
            top = ", ".join(f"{name or tid}:{used * share:.0f}%/{state}" for tid, name, state, used in rows[:6])
            total = sum(used for *_, used in rows) * share / 100.0
            out.write(f"{stamp} threads={count} running={running} process_cpu={total:.2f}core top[{top}]\n")
            # Optionally echo new metal-trace lines (the hand-off diagnostics).
            if os.path.exists(trace_path):
                try:
                    with open(trace_path, "r", encoding="utf-8", errors="replace") as tf:
                        tf.seek(trace_pos)
                        new = tf.read()
                        trace_pos = tf.tell()
                    for line in new.splitlines():
                        if line.strip():
                            out.write(f"    trace: {line[:200]}\n")
                except OSError:
                    pass
            out.flush()
        out.write(f"# game pid={pid} gone at {_dt.datetime.now().isoformat(timespec='seconds')}\n")
    print(f"wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
