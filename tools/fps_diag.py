#!/usr/bin/env python3
"""Single entry point for the Indium / FPS diagnostic tools.

Before this file the analysis lived as four disconnected manual scripts under the
(ignored) `build/fps-diag/`: `perframe.py`, `optime.py`, `thread-prof.py` and the
shell orchestrators `arm-counters.sh` / `restore-libindium.sh`. This module is the
tracked home for the analyses, so they run from a clean checkout, and a thin
dispatcher over the capture recipes.

The three analyses read the guest instrument output written to the metal trace
(`~/.darling/private/tmp/metal-trace.log`) or the running process's `/proc`. They
are strictly read-only: they never touch the game process, never inject and never
write to the runtime libraries. The capture subcommands (`arm-counters`,
`restore`, `collect-match`) only *delegate* to the existing recipes in the
capture directory; they do not implement their own runtime install.

Usage:
    python3 tools/fps_diag.py <command> [args]

Commands:
    perframe [trace] [--tail N]     blocking/CPU cost per frame, from indium-worker@
    optime   [trace] [--tail N]     replay cost by op kind, from optime@
    thread-prof [secs] [interval]   per-thread /proc profile of the running game
    report   [trace] [--tail N]     run perframe and optime together
    list                            show the tools, the capture dir and the trace
    arm-counters | restore | collect-match   delegate to the capture recipes

`FPS_DIAG_DIR` overrides the capture directory (default `build/fps-diag`).
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FPS_DIAG_DIR = Path(os.environ.get("FPS_DIAG_DIR", ROOT / "build" / "fps-diag"))
DEFAULT_TRACE = Path.home() / ".darling/private/tmp/metal-trace.log"

# The capture recipes stay outside the tree; they install a diagnostic libindium
# overlay and are deliberately not committed. The dispatcher only runs them.
DELEGATES = {
    "arm-counters": ("sh", "arm-counters.sh"),
    "restore": ("sh", "restore-libindium.sh"),
    "collect-match": ("sh", "collect-match.sh"),
    "watch": ("python3", "watch-game.py"),
    "probe-summary": ("python3", "probe-summary.py"),
}


def _split_tail(argv):
    """Pop `--tail N` out of argv, preserving the rest; returns (tail, rest)."""
    tail = None
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--tail" and i + 1 < len(argv):
            tail = int(argv[i + 1])
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return tail, rest


def _trace(rest):
    return Path(rest[0]) if rest else DEFAULT_TRACE


# --------------------------------------------------------------------------- #
# perframe: pair each indium-worker@ window with its indium-worker-per-frame@
# --------------------------------------------------------------------------- #
_PF_STAT = re.compile(r"([A-Za-z]+)\[n=(\d+) avg=(-?[\d.]+) sum=(-?[\d.]+) max=(-?[\d.]+)\]")
_PF_KV = re.compile(r"([A-Za-z/]+)=(-?[\d.]+)")


def _pf_parse_raw(line):
    return {name: (int(n), float(avg), float(s), float(mx))
            for name, n, avg, s, mx in _PF_STAT.findall(line)}


def _pf_parse_perframe(line):
    return {key: float(value) for key, value in _PF_KV.findall(line)}


def cmd_perframe(argv):
    tail, args = _split_tail(argv)
    trace = _trace(args)
    lines = trace.read_text(errors="replace").splitlines()
    windows = []
    pending_raw = None
    for line in lines:
        if line.startswith("indium-worker@"):
            pending_raw = line
        elif line.startswith("indium-worker-per-frame@") and pending_raw is not None:
            windows.append((pending_raw, line))
            pending_raw = None
    if tail:
        windows = windows[-tail:]
    if not windows:
        print(f"no instrument windows in {trace} (flag /tmp/metal-counters active? overlay loaded?)")
        return 1
    for raw, pf in windows:
        stats = _pf_parse_raw(raw)
        per = _pf_parse_perframe(pf)
        frames = per.get("frames", 0.0)
        window = per.get("window", 5.0) or 5.0
        stamp = raw.split(":", 1)[0].split("@", 1)[-1]
        print(f"\n== window {stamp}  frames={frames:.0f}  window={window:.1f}s  ({frames / window:.1f} fps)")
        if frames <= 0:
            print("   n/a: no presenting commits in this window (bench/no drawable)")
            continue

        def ms_per_frame(name):
            return stats.get(name, (0, 0.0, 0.0, 0.0))[2] / 1000.0 / frames

        def count_per_frame(name):
            return stats.get(name, (0, 0.0, 0.0, 0.0))[0] / frames

        def sum_per_frame(name):
            return stats.get(name, (0, 0.0, 0.0, 0.0))[2] / frames

        def per_second(name):
            return stats.get(name, (0, 0.0, 0.0, 0.0))[2] / window

        def count_per_second(name):
            return stats.get(name, (0, 0.0, 0.0, 0.0))[0] / window

        print("   blocking (tempo esperando, por frame):")
        print(f"     uploadFence        {ms_per_frame('uploadFenceMicros'):8.3f} ms/frame  ({count_per_frame('uploadFenceWaits'):.2f} esperas/frame)")
        print(f"     oneshotRetire      {ms_per_frame('oneshotRetireMicros'):8.3f} ms/frame  ({count_per_frame('oneshotRetireWaits'):.2f} esperas/frame)")
        print(f"     pollWait           {ms_per_frame('pollWaitMicros'):8.3f} ms/frame  ({per_second('pollWaitMicros') / 1000.0:.0f} ms/s no thread de polling)")
        print("   CPU (por frame):")
        print(f"     replaceRegion      {ms_per_frame('replaceRegionMicros'):8.3f} ms/frame  ({count_per_frame('replaceRegionCalls'):.2f} uploads/frame, {sum_per_frame('replaceRegionBytes'):.0f} bytes/frame)")
        print(f"     submitWorker       {ms_per_frame('submitMicros'):8.3f} ms/frame  ({count_per_frame('submitTasks'):.2f} tarefas/frame)")
        print(f"     pollScan           {ms_per_frame('pollScanMicros'):8.3f} ms/frame  ({count_per_second('pollEvents'):.0f} wakes/s, {count_per_second('pollCounterQueries'):.0f} queries/s)")
        print(f"     pollCallback       {ms_per_frame('pollCallbackMicros'):8.3f} ms/frame")
        print("   contexto:")
        print(f"     commits/frame      {per.get('commits/frame', 0.0):8.2f}   pendentes avg/max {per.get('pollPendingAvg', 0.0):.2f}/{per.get('pollPendingMax', 0.0):.0f}   timeouts/s {per.get('pollTimeouts/s', 0.0):.0f}")
    return 0


# --------------------------------------------------------------------------- #
# optime: break the replay translation cost down by op kind
# --------------------------------------------------------------------------- #
_OT_HEAD = re.compile(r"optime@(\d+): translation=([\d.]+)ms/s ops=(\d+) \(([\d.]+) ns/op\)")
_OT_SLOT = re.compile(r"(\w+)\[n=(\d+) avg=([\d.]+)us fast=([\d.]+)us max=([\d.]+)us slow=(\d+)/([\d.]+)%\]")


def _ot_parse(line):
    m = _OT_HEAD.search(line)
    if not m:
        return None
    epoch, msps, ops, nsop = m.group(1), float(m.group(2)), int(m.group(3)), float(m.group(4))
    kinds = {}
    for name, n, avg, fast, mx, nslow, pct in _OT_SLOT.findall(line):
        kinds[name] = dict(n=int(n), avg=float(avg), fast=float(fast), mx=float(mx),
                           nslow=int(nslow), slowpct=float(pct))
    return dict(epoch=int(epoch), msps=msps, ops=ops, nsop=nsop, kinds=kinds)


def _ot_report(win):
    print(f"optime window @{win['epoch']}: translation={win['msps']:.0f} ms/s "
          f"({win['msps']/1000:.2f} core), ops={win['ops']} ({win['nsop']:.0f} ns/op avg)")
    total_us = sum(k['n'] * k['avg'] for k in win['kinds'].values())
    rows = sorted(win['kinds'].items(), key=lambda kv: kv[1]['n'] * kv[1]['avg'], reverse=True)
    print(f"  {'kind':<16} {'calls':>9} {'avg us':>8} {'fast us':>8} {'max us':>9} {'total ms':>9} {'% time':>7}")
    for name, k in rows[:12]:
        tot_ms = k['n'] * k['avg'] / 1e3
        pct = 100.0 * k['n'] * k['avg'] / total_us if total_us else 0.0
        print(f"  {name:<16} {k['n']:>9} {k['avg']:>8.2f} {k['fast']:>8.2f} {k['mx']:>9.1f} "
              f"{tot_ms:>9.2f} {pct:>6.1f}%")
    print("  (ranked by calls x avg; 'fast' is the steady-state per-call cost)")


def cmd_optime(argv):
    tail, args = _split_tail(argv)
    if tail is None:
        tail = 3
    trace = _trace(args)
    if not trace.exists():
        print(f"trace not found: {trace}")
        return 1
    wins = []
    for line in trace.read_text(errors="replace").splitlines():
        w = _ot_parse(line)
        if w:
            wins.append(w)
    if not wins:
        print("no optime@ windows in", trace, "(was /tmp/metal-op-timing armed before the game process started?)")
        return 1
    for w in wins[-tail:]:
        _ot_report(w)
        print()
    return 0


# --------------------------------------------------------------------------- #
# thread-prof: per-thread system-time profile of the running client (read-only)
# --------------------------------------------------------------------------- #
_HZ = os.sysconf("SC_CLK_TCK")


def _tp_read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def _tp_find_game_pid(tries=3600):
    """The client runs inside Darling; its guest-process comm shows up as the Riot process name."""
    for _ in range(tries):
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            cl = (_tp_read(f"/proc/{pid}/cmdline") or "").replace("\0", " ")
            if "Game/LeagueOfLegends.app" in cl and "LeagueClient" not in cl:
                try:
                    if len(os.listdir(f"/proc/{pid}/task")) > 20:
                        return int(pid)
                except OSError:
                    pass
        time.sleep(0.5)
    return None


def _tp_snap(pid):
    out = {}
    for tid in os.listdir(f"/proc/{pid}/task"):
        stat = _tp_read(f"/proc/{pid}/task/{tid}/stat")
        if not stat:
            continue
        close = stat.rfind(")")
        rest = stat[close + 2:].split()
        status = _tp_read(f"/proc/{pid}/task/{tid}/status") or ""
        vol = invol = 0
        for line in status.splitlines():
            if line.startswith("voluntary_ctxt_switches:"):
                vol = int(line.split()[1])
            elif line.startswith("nonvoluntary_ctxt_switches:"):
                invol = int(line.split()[1])
        out[tid] = (
            (_tp_read(f"/proc/{pid}/task/{tid}/comm") or "").strip(),
            int(rest[11]),   # utime
            int(rest[12]),   # stime
            int(rest[7]),    # minflt
            vol, invol,
        )
    return out


def cmd_thread_prof(argv):
    seconds = float(argv[0]) if len(argv) > 0 else 120.0
    interval = float(argv[1]) if len(argv) > 1 else 2.0
    pid = _tp_find_game_pid()
    if pid is None:
        print("nao achei o processo do jogo")
        return 1
    print(f"pid={pid}; amostrando {seconds:.0f}s a cada {interval:.0f}s")
    log = FPS_DIAG_DIR / "thread-prof.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    prev = _tp_snap(pid)
    end = time.time() + seconds
    out = open(log, "a")
    while time.time() < end:
        time.sleep(interval)
        cur = _tp_snap(pid)
        rows = []
        for tid, v in cur.items():
            p = prev.get(tid)
            if not p:
                continue
            du = (v[1] - p[1]) / _HZ / interval
            ds = (v[2] - p[2]) / _HZ / interval
            mf = (v[3] - p[3]) / interval
            iv = (v[5] - p[5]) / interval
            rows.append((du + ds, du, ds, mf, iv, v[0]))
        prev = cur
        rows.sort(reverse=True)
        line = f"{time.strftime('%H:%M:%S')} top: " + " | ".join(
            f"{c}:{t:.2f}core(u{u:.3f}/s{s:.3f}) mf={mf:.0f}/s inv={iv:.0f}/s"
            for t, u, s, mf, iv, c in rows[:6])
        print(line, flush=True)
        out.write(line + "\n")
        out.flush()
    out.close()
    return 0


# --------------------------------------------------------------------------- #
# dispatcher
# --------------------------------------------------------------------------- #
def cmd_report(argv):
    tail, args = _split_tail(argv)
    trace = _trace(args)
    per_args = [str(trace)] + (["--tail", str(tail)] if tail else [])
    print("# perframe")
    rc = cmd_perframe(per_args)
    print("# optime")
    rc2 = cmd_optime(per_args)
    return rc or rc2


def cmd_list(argv):
    print(f"capture dir : {FPS_DIAG_DIR}")
    print(f"trace       : {DEFAULT_TRACE}")
    print("analyses (self-contained):")
    print("  perframe, optime, thread-prof, report")
    print("capture recipes (delegated, must exist in the capture dir):")
    for name, (interp, script) in DELEGATES.items():
        present = "ok" if (FPS_DIAG_DIR / script).exists() else "missing"
        print(f"  {name:<14} {script}  [{present}]")
    return 0


def cmd_delegate(name, argv):
    interp, script = DELEGATES[name]
    path = FPS_DIAG_DIR / script
    if not path.exists():
        print(f"{name}: {path} not found (set FPS_DIAG_DIR)", file=sys.stderr)
        return 1
    return subprocess.call([interp, str(path), *argv])


COMMANDS = {
    "perframe": cmd_perframe,
    "optime": cmd_optime,
    "thread-prof": cmd_thread_prof,
    "report": cmd_report,
    "list": cmd_list,
}


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    name, rest = argv[0], argv[1:]
    if name in COMMANDS:
        return COMMANDS[name](rest)
    if name in DELEGATES:
        return cmd_delegate(name, rest)
    print(f"unknown command: {name}\n", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
