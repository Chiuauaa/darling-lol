# Worklog — FPS on the NVIDIA machine: game is CPU-bound

Date: 2026-10-18. Status: **diagnosis complete, fixes open.** The black game
window is closed (see [WORKLOG-OpenGL-EGL.md](WORKLOG-OpenGL-EGL.md) and
[troubleshooting](TROUBLESHOOTING.md#nvidia-the-window-attaches-and-the-frame-is-dropped-fixed-2026-10-18));
this file records why the FPS on this machine is low, one crash caused during the
investigation, and the experiments queued for the next session.

> **Second session, same day (20:00–21:10) — read
> [the section below](#second-session-20002110-the-frame-is-latency-bound-not-cpu-starved)
> first.** With internal instruments (per-frame CSVs, per-site wait counters, GPU
> clocks) the picture changed: the box **is** saturated, but the game's own threads
> are **not** CPU-starved (`run_delay` 1–2%), the **GPU idles** (23–34%, P5,
> 885–911 MHz, 15–18 W), the **driver call is free** (`vkQueueSubmit2` ≈ 0 ms) and
> the **present path is cheap** (6.2 ms/frame). A 59 ms frame is spent blocked in
> `drain@commit` (60–70% of the presenting thread's wall time) waiting on the
> single-threaded deferred-replay worker, with the GPU waiting behind it. Two
> knobs that remove that wait changed nothing, so it is a **symptom**. Title
> "CPU-bound" is therefore too strong; see the new section for the corrected
> model and the queued tests.

This is a working log, not curated documentation. Fold durable conclusions into
`STATUS.md` / `SETUP.md` / `TROUBLESHOOTING.md` when the work is finished.

## Objective

Play League of Legends under Darling with the match window rendering (done) and
understand/raise the in-game FPS. The user's point throughout: the same i3-8100
plays League at a locked 60 FPS on Windows 10, so the hardware is not the
problem — the gap is Darling-side overhead.

## Environment

| | |
|---|---|
| Host | CachyOS, KDE Plasma on Wayland (`kwin_wayland`) |
| GPU | NVIDIA GTX 1070, driver 580.178.04 |
| CPU | Intel **i3-8100 — 4 threads, no SMT** |
| Display | HDMI-A-2, a single mode: **1360x768 @ 59.80 Hz** |
| Memory | 15.9 GiB, ~1.6 GiB swap in use |
| Guest game | League of Legends `16.20.824.8524` (Mac Beta), region `BR1` / `pt_BR` |
| Launcher env | `RCLOL_REFRESH_HZ=60`, `RCLOL_GPU_DIRECT_PRESENT=1`, `RCLOL_MOUSE_CONFINEMENT=1`, `__GL_MaxFramesAllowed=1`, `__GL_YIELD=NOTHING`, `__GL_THREADED_OPTIMIZATIONS=0` |
| In-game video | `Width=1360 Height=768`, `ShadowQuality=2 EnvironmentQuality=2 EffectsQuality=2 CharacterQuality=2 VideoQuality=0 FrameCapType=2` |

The runtime referenced here is the clean overlay set (OpenGL sha256
`12399a58c7bc13dd…`, QuartzCore sha256 `a42b32664b98bb89…`); `python3
scripts/prepare.py --check-only` reports "All 30 component patches validated".

## What was validated

- A practice match on Summoner's Rift rendered the full HUD at **59 FPS / 9 ms**
  with `GAMESTATE_GAMELOOP` and **zero** `Metal Device timed out` entries. The
  draw-buffer fix is in `CGLContextMakeCurrentAndAttachToWindow`.
- Window-restart procedure to activate an overlay, used repeatedly this session:
  `darling shutdown`, then `sh scripts/run.sh` (background). The League client
  logs in and reaches `reasons.play.enabled` in ~37 s on this machine.

## Why the FPS is low (measured)

**Not the GPU.** The GTX 1070 idled at **14–16%** utilisation, ~40 W, 1506 MHz
while the game ran at 16–33 FPS.

**Not disk.** `iostat` during client load showed `%util` on the game disk of a
few percent and `wa=0%` in `vmstat`.

**The display caps at 60.** The only HDMI mode is 59.80 Hz, so with "Wait for
Vertical Sync" on, a frame that misses 16.6 ms quantises to 30/20 FPS. The HUD
"59" early in a match is that cap.

**The CPU is saturated.** With the match running: `load` 8–12 on 4 threads, CPU
time split roughly **57% user + 27% system**, only ~12.6% idle. The 27% system
time is the syscall/translation overhead, not the game's own work.

Where the CPU went during a match (host PIDs, `ps`/`top` samples):

| Consumer | CPU |
|---|---|
| Game (`mldr`: main ~27% + render ~44%) | ~0.83 core |
| **League/Riot client Chromium** (`CrBrowserMain` ~45% + `CrRendererMain` ~21% + `CrGpuMain` ~19%, up to ~1.8 cores while the client loads) | ~0.85–1.8 core |
| `darlingserver` | ~0.3–0.5 core |
| `plasmashell` + `kwin_wayland` | ~0.3 core |
| Background (`localsearch-3`, Discord, Brave, IDE) | ~0.3–0.5 core |

Consequences:

- The game's own threads total ~0.83 core, i.e. they are **not** each pegged;
  they finish a frame's work but the frame still takes 30–60 ms because the four
  threads are oversubscribed and the hand-off/present waits queue behind
  everything else.
- FPS degraded with match progress: 59 (~0:50) → 39 (~2:08) → 16–33 (6–12 min),
  consistent with more entities/effects raising the game's per-frame CPU while
  the background load stays.
- `renice 19` on the client's Chromium PIDs changed nothing (game CPU
  82.9% → 83.0%, FPS unchanged), so it is not scheduler ordering alone: the total
  demand exceeds the 4 threads.
- Two `Metal Device timed out giving us a Drawable to present. GPU hung?` at
  36.9 s and 37.9 s (transient at match start, not progressive).
- Reference machine: the Ryzen 5 5500 / RX 6600 does 118–135 FPS with the same
  runtime; the i3-8100 has far less single-thread and only 4 threads.

**Client load time.** From login to "Play enabled" is ~37 s here; the largest
single stall (17 s) was **network**, not CPU (`Failed to get activity data` /
static-resource fetch). The rest is CPU contention.

## Crash caused during the investigation (resolved, documented)

Arming `/tmp/metal-no-drawable-vram` (as a perf candidate) together with
`/tmp/metal-debug-waits` made **every** game start `abort()` on NVIDIA:

- 5 starts in a row died ~2 s after appearing, in a crash-loop; no window.
- `dserver.log`: `LOLSIG processSignal bsd=6 linux=6 code=-6` (SIGABRT) for the
  `.../Game/LeagueofLegends.app/Contents/MacOS/LeagueofLegends` process.
- `*_r3dlog.txt` stopped at `Metal Device Approx VRAM: …`, before
  `Using X3D Platform: Metal` / `RecreateOwnedResources`.
- The Riot Client wrote `Logs/GameCrashes/<guid>.run/__sentry-event`
  (`level=fatal`, `platform=native`).
- Proof it was the flag: `metal-device.log` printed `drawable-vram=on` /
  `storage=vram` for the healthy run earlier the same day and
  `drawable-vram=off (file:/tmp/metal-no-drawable-vram)` for all five crashing
  attempts; the game build was identical (`16.20.824.8524`).

Removing the guest files restored play. See
[troubleshooting](TROUBLESHOOTING.md#nvidia-tmpmetal-no-drawable-vram-aborts-the-game-2026-10-18)
and [setup](SETUP.md#metal-and-indium-overlays). **Lesson: arm one experimental
knob at a time.**

## Other observations

- `gamemoderun` is installed but ineffective: `ERROR: ld.so: object
  'libgamemodeauto.so.0' from LD_PRELOAD cannot be preloaded`. `scripts/run.sh`
  selects it whenever it is on `PATH` (`RCLOL_GAMEMODE=auto`); setting
  `RCLOL_GAMEMODE=0` removes the noise, or install `libgamemodeauto` to actually
  get the CPU governor/nice hints.
- `lsfg-vk` (a Vulkan frame-generation layer) fails every frame with
  `filesystem error: cannot create directories: Permission denied
  [/Users/chiuaua/.config/lsfg-vk]`. It never initialises, but if it is installed
  as a Vulkan implicit layer it is worth confirming it cannot hook the game.
- `plasmashell` sat at ~20–23% CPU continuously, including on a fresh, idle boot —
  abnormally high for a panel. Its top threads are `QSGRenderThread` (~18%) plus
  `QFFmpeg::Stream`/`QFFmpeg::AudioR`/`QFFmpeg::Demuxer`, i.e. plasmashell is
  continuously re-rendering and decoding media: look for an animated/video
  wallpaper or a media widget. Recovering it is worth ~0.2 core — exactly the
  headroom the game needs.
- **Vanguard.** Written up separately in [VANGUARD.md](VANGUARD.md). Short
  version: the macOS client ships a Vanguard integration (Riot Client plugin
  `rcp-be-lol-vanguard` plus version/service probes in
  `libRiotClientFoundation.dylib`) and every probe fails cleanly here
  (`Failed getting installed version of Vanguard: Unsupported operating system`,
  `Failed to get vanguard service status: Unimplemented`), with **no
  `*vanguard*`/`vgk`/`vgc` file installed anywhere under `~/.darling`**. The UI
  shows `Vanguard Modal region: BR` and briefly disables Play with `Vanguard is
  not connected or enabled`; this is **normal** (every working 2026-10-18 launch
  did it) and the modal is dismissible. Treat Vanguard as read-only: no game
  process/memory manipulation, no input automation, no `SIGSTOP`/`SIGCONT` on the
  game, and never spoof its service or libraries. All instrumentation used here is
  log reading, `wmctrl`/`spectacle` and `/proc/<pid>/task/*/stat` (scheduling
  only) — never game memory.
- The repeated League-client churn at startup (`Terminating via POST
  /process-control/v1/process/quit`, `Failed to find app process … terminating
  ux process`) is **normal**: the working 12:42, 01:41 and 13:41 launches all
  showed `terminating_ux=1 quit=1 foundation=1`. The Riot Client starts a
  throwaway League client, closes it, then starts the real one.

## Second session, 20:00–21:10: the frame is latency-bound, not CPU-starved

Same machine, same runtime, one `darling shutdown` + `sh scripts/run.sh` in the
middle (log `/tmp/opencode/run4.log`). Everything below is measured, not inferred;
each number names the instrument that produced it.

### Instruments (all opt-in, all read-only, all reusable)

Guest flags live in `/tmp` **inside the guest** = `~/.darling/private/tmp` on the
host. Arm them with `darling shell touch` (creating them from the host can be
invisible to a running guest process through the overlay's negative cache). A
`darling shutdown` **wipes `~/.darling/private/tmp`**, so re-arm after every
namespace restart.

| Flag (guest `/tmp`) | What it turns on | Cost |
|---|---|---|
| `metal-debug-timing` | `mtl-timing@<epoch_s>` (Metal side) and `indium-timing@<s>` (Indium side) blocks in `metal-trace.log`, every ≥5 s | negligible |
| `metal-debug-waits` | `waits@<s>` blocks: per-site `n` / `sum` / `max` of *actual* blocks (`drain@commit`, `presentDispatchWait`, `oneshotFence`, `nextDrawable`, `queueMutex`) | negligible |
| `metal-frame-interval-capture` | Indium: 4096 frames × (`commit_ns, submitted_ns, presented_ns, completed_ns`) → `/tmp/metal-frame-intervals.csv`; CA side: 2048 presents × (`queued_ns, render_start_ns, render_done_ns, flush_done_ns`) → `/tmp/metal-present-intervals[-N].csv`, up to 8 blocks | one CSV dump |

Fields, so the next reader can interpret them:

- `gpuCommitToComplete` (metal.patch, in `MTLCommandBuffer.commit`) — **CPU
  round-trip**: from the start of `commit()` to the completion handler firing
  (`addCompletedHandler`). It is *not* GPU busy time; `n` = commits in the window.
  It tracks the frame time (48–73 ms at a 59 ms frame), so it is a dependent
  measure.
- `commitCall` — CPU time spent inside `commit()` on the game's thread: **0.0 ms**
  (the work was posted to the worker).
- `pass_<WxH>_f<fmt>_load<L>` — per-render-pass GPU time: **0.0 ms** each.
- `submitToCallback` (indium) — per commit, submit → completion callback: 6–8 ms
  avg, 20–32 ms max.
- `vkQueueSubmit2` — **avg 0.0 ms, max 0.1–1.8 ms**: the NVIDIA driver call is free.
- `handlersDuration` ≈ 0. `waitSemaphoresPerSubmit` = 1.0 (constant, meaningless).
- CA side (`timing@`): `prepareRenderInterval`, `prepareRenderTotal`,
  `mainBlockRender`, `mainBlockFlush`, `nextDrawableWait`, `rendererRender`,
  `synchronizeRender`, `assignTextureIds`.
- `indium-submit-stats.log` — one line per **1024 presents** with a timestamp and
  `commits_per_frame` / `submits_per_frame`; FPS = 1024 / Δt.

Pitfalls found the hard way:

- `mtl-timing`'s print state (`stats`, `last`) is **per translation unit**, so
  consecutive lines can be 1 s apart and belong to different 5 s windows. Deriving
  FPS from consecutive lines produces garbage (a spurious "58 FPS" this session);
  use one stream (lines carrying `gpuCommitToComplete`) or the CSVs.
- Flags read with `access()` **on the hot path** can be toggled live, without any
  restart: `/tmp/metal-async-no-frame-sync` is checked on every presenting commit.
  Flags cached in a `static` need a new game process: `presentDispatchWait`
  (`metal-present-dispatch-wait`), all timing flags, `AsyncEncode`, the device
  decisions. A game process is created per match load, so "leave and re-enter the
  practice" is usually enough — no namespace restart.
- **`AsyncEncode` is ON by default for the game process**
  (`leagueGame && access("/tmp/metal-no-async-encode") != 0`): every command
  buffer's encoding/replay is deferred to the single `SubmitThread` worker, and
  the presenting commit waits for that worker. This is the architecture the
  numbers below describe.

### Frame budget, baseline match (17–19 FPS ≈ 59 ms/frame)

`metal-frame-intervals.csv` (4096 frames, /tmp/opencode/baseline/) and
`metal-present-intervals.csv`:

| Stage | avg | p50 | p90 | max |
|---|---|---|---|---|
| commit → submitted (worker) | 2.13 ms | 1.30 | 4.50 | 16.2 |
| submitted → presented | 1.47 ms | 0.63 | 4.60 | 13.9 |
| presented → completed | 1.89 ms | 1.89 | 5.55 | 25.9 |
| **commit → completed (whole Metal pipeline)** | **5.50 ms** | 5.03 | 9.35 | 26.8 |
| frame interval (commit → commit) | 59.35 ms | 54.33 | 86.7 | 244.6 |

| CA present path | avg | p50 | p90 | max |
|---|---|---|---|---|
| queued → renderStart | 3.82 ms | 2.81 | 8.06 | 16.9 |
| renderStart → renderDone | 2.16 ms | 1.23 | 5.11 | 16.4 |
| renderDone → flushDone | 0.23 ms | 0.12 | 0.48 | 8.1 |
| **queued → flushDone (present)** | **6.22 ms** | 5.50 | 10.98 | 23.7 |
| present interval | 52.6 ms | 49.0 | 75.2 | 160.3 |

So of a 59 ms frame: **~5.5 ms is the Metal pipeline**, **~6.2 ms is the
present**, and the presenting thread is blocked **`drain@commit` n≈62–110 per 5 s,
`sum` 3.0–3.6 s per 5 s (60–70% of that thread's wall time), max 34–212 ms**.

### What is now ruled out (each with its number)

- **GPU** — `nvidia-smi`: 21–34% utilisation, **P5, 885–911 MHz** (idle clocks, boost
  is ~1.7 GHz), **15–18 W**. The GPU waits, it does not work.
- **Vulkan driver call** — `vkQueueSubmit2` avg 0.0 ms, max ≤1.8 ms.
- **Present/composite path** — 6.2 ms/frame; `nextDrawableWait` avg 0 ms, max 1 ms.
- **The frame-end wait as the cause** — see the two A/Bs below: removing it
  changed nothing.
- **CPU starvation of the game** — with the box at 3.73/4 cores busy,
  `procs_running` averaging 16.3 and loadavg 16.3, the game's threads show
  `run_delay` (in `/proc/<tid>/schedstat`, "runnable but not on a CPU") of only
  **1.4–2.2%**. The game gets CPU when it wants it; it is *blocked*, not starved.
  This is why "close the background apps" is **not** the lever it looked like.
- **Occlusion throttling the client** (from the first session) — iconifying the
  Riot Client did not reduce its CPU (1.06 → 1.16 core); the work continues
  unmapped. (The *game* window being covered by the Konsole is still untested;
  see open items.)
- **Submit batching not in use** — it is on by default (`commits_per_frame`
  19–31 → `submits_per_frame` 8–11.6), `/tmp/metal-no-submit-batch` is the off-switch.

### Where the frame actually goes

Per-thread, inside a match (`/proc/<tid>/stat` + `schedstat`, 10 s windows):

| Thread | CPU | state |
|---|---|---|
| **Submit worker** (single thread, `SubmitThread::loop`) | **40% (≈24 ms/frame)**, R 66% of samples | the busiest thread in the game |
| Presenting/main thread | 15% (≈9 ms/frame) | **S 64%**, almost all of it in `drain@commit` |
| every other game thread | <2% each | 95–99% sleeping |

- Game total ≈ 0.53–0.64 core, split **user 12.5% / system 41.0%** — the game's own
  work is *syscall/RPC-dominated*, not compute.
- `darlingserver` 27–34% (user 12.9 / sys 14.2).
- Model: record on the main thread (~9 ms) → **deferred replay on the one worker
  (~24 ms)** → submit (free) → GPU (fast, idle) → CA present (6 ms) → compositor,
  with the presenting thread parked in `drain@commit` for the rest. The frame is
  set by this **serial chain and its round-trip latencies**, not by any saturated
  resource.

### The two knob A/Bs

| Knob | Effect on the trace | FPS |
|---|---|---|
| `/tmp/metal-present-dispatch-wait` (narrow wait: only this commit's own task, not the whole queue) | wait site becomes `presentDispatchWait`, n 161–205 per 5 s, sum 3.2–3.5 s per 5 s — still 60–70% of the wall time | user: **"same average FPS"** |
| `/tmp/metal-async-no-frame-sync` (skip the frame-end sync entirely) | `waits@` counters **stop** — `drain@commit` disappears from the process | ~14.6 FPS, i.e. **no gain** (baseline 17–19) |

Removing the wait does not raise the frame rate, so the wait is the *symptom* of a
limit downstream (the 19 commits still have to be replayed, and the frame still
has to reach the screen). Any future fix must cut the work or the chain, not the
`drain()` call.

### Machine saturation, and the one big Darling-side CPU leak

10 s `/proc/stat` + per-pid deltas during a match: **3.73 of 4 cores busy, 6.7%
idle**, no steal (bare metal), no cgroup quota/throttling, cpufreq pinned at 3.6
GHz. `procs_running` avg 16.3, loadavg 16.3. **irq 13.7% of all CPU time** —
`LOC` ~13.8 k/s and `RES` ~9.8 k/s (timer + reschedule IPIs); the NVIDIA IRQ is
only 841/s, so there is no GPU interrupt storm.

| Consumer | CPU |
|---|---|
| Riot Client renderer (`CrRendererMain`, idle launcher UI) | **69–81%** (six `ThreadPoolForeground` threads at 7–17% each) |
| Game (`mldr`) | 53–63% |
| `darlingserver` | 27–47% |
| League Client browser (`CrBrowserMain`) | 32–52% |
| 2 × `CrGpuMain` (Riot + League) | 25–27% each |
| KDE monitor helper `ksgrd_network_helper` | 5–38% (**killed this session**) |
| plasmashell, kwin_wayland, konsole, Brave, IDE | ~0.3 core together |

The Darling-hosted Chromium clients together hold **~1.65–1.9 cores** — the
largest identifiable Darling-side CPU waste on this box (an idle launcher UI has
no business costing a full core; on Windows/macOS it does not). Measured the
other way round, though, it is **not** what caps the game: the game's threads are
not starved, and `renice`/freezing attempts in the first session did not move the
FPS. Both facts belong in the record: it is a real Darling-side bug worth fixing,
and it is not the FPS limiter.

### Tooling

- `tools/game-thread-probe.py` was **broken and now works**: the game host process
  is `mldr` (kernel truncates comm to 15 chars) and the bundle is
  `LeagueOfLegends.app` with a capital `O`, so the probe never attached. It now
  matches the argv (`leagueoflegends.app/contents/macos/leagueoflegends`,
  case-insensitive) as well as the comm.
- `/tmp/opencode/monitor2.py` (scratch, not a repo tool): 5 s timeline of
  trace-derived FPS, `gpuCommitToComplete`, `nvidia-smi` util / SM clock / power,
  the game's thread states, the newest wait counters and the top game threads.
- Session artifacts: `/tmp/opencode/baseline/` (the CSVs above plus
  `trace-baseline.log`), `/tmp/opencode/monitor2.log`.
- **Not done on purpose:** no `SIGKILL`/`SIGSTOP` on the game or the clients, no
  `ptrace`/`strace`/`perf`, no memory reads. Only `/proc` scheduling metadata,
  `nvidia-smi`, log reading and `wmctrl`/`spectacle`.

### Open items after this session

1. **Quantify the deferred path** — A/B `/tmp/metal-no-async-encode` (round-3
   behaviour: encode on the game thread, no worker, no `drain`). If the FPS is
   flat, the replay is not the critical path and the chain/latency model needs
   revision; if it is worse, the worker earns its keep and the fix must be inside
   it (parallel replay / lower per-commit cost).
2. **Find the real pacer, given an idle GPU.** Prime suspect: the compositor.
   The CA layer was compositing far less often than the game presented
   (`prepareRenderInterval` 76 ms, then 221 ms with max 1881 ms, versus ~14
   presents/s), and the game window sits **behind the user's Konsole** (Wayland
   native over Xwayland). Test: keep the game window in front (raise it with
   `wmctrl`; stacking only) and compare the present rate from the same
   instruments. If occlusion throttles, most of the "low FPS" is a window
   stacking artifact and the FPS HUD is not comparable between runs.
3. **Price the Darling RPC tax.** The game's CPU is 41% system and `darlingserver`
   is 27–47%: a per-frame round-trip cost on the critical path.
   `/tmp/rclol-game-decisions.log` is **not being written** (worth checking why);
   try small `/tmp/rclol-rpc-spin-us` values (spinning may hurt on a saturated
   box) and look for RPC batching/round-trip reduction instead.
4. **Fix the Chromium clients' CPU** (~1.65–1.9 cores for idle UIs). Find the work
   (six `ThreadPoolForeground` threads rasterising in the Riot Client renderer;
   software decode possible) before choosing a fix. This is a visible,
   user-facing Darling-side win even if it does not raise the game's FPS.
5. **Keep the 60 Hz quantisation in mind** for any FPS claim: the only HDMI mode
   is 59.80 Hz, `FrameCapType=2`, and "Wait for Vertical Sync" quantises a missed
   frame to 30/20. Report the scene with every FPS number (base vs lane differs
   by 2× here).

## Open items for the next session

> Superseded by *"Open items after this session"* above (2026-10-18, second
> session). Kept for the record: item 1 ("restore CPU headroom") is now known to
> be **not** the FPS lever — see the second-session section.


1. **Restore CPU headroom** (biggest lever): close/pause Brave, `localsearch-3`
   and Discord for a clean run; investigate `plasmashell` at ~23%.
2. **Confirm the frame-time limit is CPU, not the hand-off.** Run the game with
   `tools/game-thread-probe.py` (below) and check whether the game's main/render
   threads are near 100% (`R`) or mostly sleeping (`S`) at low FPS. If they
   sleep, the remaining levers are the present/hand-off path; if they run, it is
   contention.
3. **A/B safe knobs one at a time** (each needs a game start, remove before the
   next): in-game "Wait for Vertical Sync" off and/or a higher frame cap (removes
   the 60→30/20 quantisation); `RCLOL_REFRESH_HZ`; `__GL_MaxFramesAllowed`;
   `/tmp/metal-present-dispatch-wait`; `/tmp/rclol-rpc-spin-us` (small values;
   spinning may hurt on a saturated CPU). **Never** `/tmp/metal-no-drawable-vram`
   on NVIDIA.
4. **Lower in-game video quality** (shadows/effects/environment/character) to cut
   the game's per-frame CPU; the GPU is idle so the visual cost is low.
5. ~~**Deliver the Vanguard written analysis.**~~ **Done — see
   [VANGUARD.md](VANGUARD.md)** (how the client-side check works, why it is inert
   on macOS/Darling, the anti-cheat expectations and the read-only safety rule).

### Per-thread sampler — now a repo tool

`tools/game-thread-probe.py` samples `/proc/<game pid>/task/*/stat` every
`--interval` seconds, reports each thread's `%CPU` (from the `utime+stime` delta)
and how many threads are in state `R`, and optionally tails
`~/.darling/private/tmp/metal-trace.log` when the `metal-debug-waits` diagnostic
is armed. It finds the game by task name **or** argv (the Darling loader's
process name is not "LeagueofLegends", so the argv fallback matters) and reads
only scheduling metadata — never game memory. Run it in the background while you
play, then stop it with the stop file:

```sh
rm -f /tmp/opencode/stop-probe
python3 tools/game-thread-probe.py --interval 2 --out /tmp/opencode/game-threads.log &
# ... play ...
touch /tmp/opencode/stop-probe
```

## Third session, 22:05–22:30: the frame is one core of replay, not the pipeline

The runtime had been shut down; it was restarted with the same diagnostics plus a
new one (last subsection). A practice match was measured from the fountain
outwards, which finally gives both ends of the range in **one process**: 60.4 FPS
standing in base and 23 FPS once the lane and minions are live, same settings.

### The pipeline stops mattering above ~26 FPS

`metal-frame-intervals.csv` (4096 frames, 125 s, the whole drift from 50 to 23 FPS):

| frames | FPS | `commit->completed` avg | p90 |
|---|---|---|---|
| 0–800 | 50–53 | 2.3–2.5 ms | 3.8–4.6 ms |
| 1200–2000 | 34–38 | 2.3–2.6 ms | 4.2–4.5 ms |
| 2400–3200 | 27–28 | 2.1 ms | 3.9–4.0 ms |
| 3600–4000 | 23 | 1.9 ms | 4.1 ms |

The whole Metal round trip is ~2 ms and **does not grow while the frame grows
2.5×**; the CA present is flat at 2.6–2.8 ms (`metal-present-intervals*.csv`,
2048 presents/block, onset queued→renderStart 1.6–1.9 ms). GPU: 7–15 %,
1126 MHz, 36–37 W, P2–P5 — idle and downclocked while the game runs at 23 FPS.

### What actually paces the frame

- `indium-submit-stats.log`: `commits_per_frame` **16.8 → 23.8 → 35.7** as the
  scene fills, and FPS × that ≈ 970–1020/s in every window, i.e.
  `FPS ≈ 1000 / commits_per_frame`. `submits_per_frame` is only 6–11 (the
  submit batch merges them), and the whole frame is one `vkQueueSubmit2`.
- The submit worker is ~1 core (62–70 % of one) and the presenting thread sits in
  `drain@commit` **56–70 % of its wall time** in *both* the 60 FPS and the 23 FPS
  states (drain sum 2.8 s/5 s at 60 FPS, 3.4 s/5 s at 23 FPS). This corrects the
  earlier reading that the worker was idle half of the drain: measured together,
  the drain length *is* the worker's replay time.
- So a frame is `record (~13 ms on the game thread) + replay (~26 ms on the one
  worker)`, serialized = ~39 ms at 23 FPS. The game itself is not starved: box
  measured at 3.06/4 cores busy, **0.94 core idle**, game 1.07 core, League
  client `CrBrowserMain` 0.53 core, `darlingserver` 0.19 core.
- `submitted→completed` per command buffer is the GPU completion, but with the
  GPU idle it just tracks the CPU: `waitSemaphoresPerSubmit` 1.0 ms/frame.

### Async-encode A/B in the light scene (live knob)

| block | cmd/s | commit latency | game CPU | hottest threads | GPU |
|---|---|---|---|---|---|
| A1 baseline | 1017.6 | 8.6 ms | 101 % | worker 60 %, main 28 % | 15 %, 1126 MHz |
| B `metal-no-async-encode` | 932.9 | 3.2 ms | 100 % | main 87 %, worker ~0 | 5 %, 1506 MHz |
| A2 baseline | 1055.8 | 13.0 ms | 103 % | worker 65 %, main 25 % | 8 %, 1126 MHz |

No throughput difference at the 60 FPS cap (A1 and A2 differ by 4 % themselves):
the knob moves *where* the encode runs, not how much work there is. The
heavy-scene A/B is still open and needs an uncapped scene.

### New instrument: per-call translation cost

`/tmp/metal-op-timing` (in `patches/metal--deps--indium.patch`, header
`private-include/indium/deferred-render-encoder.private.hpp`) times every op in
`replay()` and aggregates per Metal call kind, plus `encCreate`/`encEnd` per
render pass, printing one line every 5 s:

```
optime@<epoch>: translation=<ms/s> ops=<n> (<ns>/op) encCreate[n= avg= max=] encEnd[...] SetPipeline[...] DrawIdx[...] ...
```

Overhead while armed is two `clock_gettime` per op (~50 ns), so subtract that
from the small kinds. Built with
`python3 build/runtime/tools/build-riot-indium-runtime.py`, installed with
`sh build/runtime/tools/install-riot-metal-pair.sh` (the Metal half was
byte-identical; only `libindium.dylib` changed), activated by `darling shutdown`
+ `sh scripts/run.sh`. Arm it *before the game process starts*, together with
`metal-debug-timing`, `metal-debug-waits` and `metal-frame-interval-capture`
(`darling shell touch /tmp/...`); `darling shutdown` wipes the guest `/tmp`.

## Constraints / conventions

- Keep patches minimal; source changes live in `patches/*.patch`; never reset a
  checkout to make a patch apply; validate with
  `python3 scripts/prepare.py --check-only`.
- Rebuild/install only the changed component; activating an overlay needs a full
  `darling shutdown` + `sh scripts/run.sh`.
- Short answers; never print `remotingAuthToken` / `--riotclient-auth-token`
  (one was leaked by a log grep this session — redact by value, not by pattern),
  `machineId`, or account data.
- Do not touch the game process in relation to Vanguard: no memory, no injection,
  no input automation.

## Fourth session, 2026-10-19 (no gameplay needed to conclude): the worker is kernel-bound

A short match was captured with the **stock** build and only `metal-debug-timing` +
`metal-debug-waits` armed (in-guest flags), reading the guest trace from the host
(`~/.darling/private/tmp/metal-trace.log`). This session adds a per-thread view and a
new counter to the diagnostic overlay; **no change to `patches/` and the runtime was
restored to the stock `libindium` (md5 `89e7338998e4d4de64192fa1fe3edf63`)**.

### The busiest thread burns kernel time, not memory

Host `/proc/<tid>/stat` deltas during a live match:

| Thread | CPU | split | faults | ctxt switches |
|---|---|---|---|---|
| hot worker | **0.55–0.68 core** | user 0.06 / **sys 0.53** | **~0 minor-faults/s** | invol ~1050–1380/s |
| game main (`mldr`) | 0.20–0.27 core | user 0.17 / sys 0.04 | — | parked in `futex_wait` |

A `State: R` snapshot (never parked, `wchan=0`) plus ~0 minor faults rules out the
allocation-churn theory for this thread: it is busy in **syscalls**, being preempted
while runnable. The naming overlay (previous session) puts this thread at
`indium-submit` 50–60 % core — i.e. it is the **deferred-replay worker**, consistent
with the third-session model (frame = record + replay, serialized). `drain@commit`
remains the main thread's block (`n≈184–205`/5 s, `sum≈2.9–3.2 s`/5 s, max 24–50 ms).

### What the layer counters said

- `vkQueueSubmit2` avg **0.0 ms**, max 0.1 ms — the driver queue call is free (again).
- `submitToCallback` avg 3.8–4.1 ms, max 11.8–20.8 ms; `commitCall` avg 0.7 ms,
  max 36.8 ms; `gpuCommitToComplete` avg 11.1–13.6 ms, max ~50 ms; per-pass GPU time
  0 ms. No `slow-cmdbuf` lines (>0.3 s commits).
- `waitSemaphoresPerSubmit` = 1.0 (constant; uninformative, per the field note above).

So the worker's kernel time is **not** `vkQueueSubmit2`. Prime suspects per commit,
each with a measured kernel cost in the earlier microbench: `vkCreateSemaphore` /
`vkDestroySemaphore` (exportable ≈ 108 µs) and any `vkAllocateMemory`/`vkFreeMemory`
(≈ 142 µs / 4 KB). The code shows binary semaphores have **no pool**: every commit's
read/write textures `vkCreateSemaphore` in `getBinarySemaphore` and
`vkDestroySemaphore` in `putBinarySemaphore` (the release happens from the GPU
completion callback, so *time of release* is safe to pool from).

### Overlay extended to attribute it

`/tmp/opencode/indium-src-counters` now counts `binarySemCreate` /
`binarySemCreateExport` / `binarySemDestroy` (+ `…Micros`) and the per-frame line
gained `binarySemC/frame`, `binarySemCE/frame`, `binarySemD/frame`,
`binarySemMs/frame`. Rebuild with `python3 /tmp/opencode/build-counters-overlay.py`.

### Reproducing offline failed

Launching only the Riot Client does **not** reproduce the workload: its processes sit
idle (`CrGpuMain` ~0 %; `indium-submit` exists but unused) and produce **no**
`indium-worker@` dumps, and there is no `indium-poll` thread (the client's CEF path
never drives `pollEvents`). The heavy replay is game-specific; the next session needs
a real match.

### Next-session protocol

1. `sh /tmp/opencode/arm-counters.sh` (installs the counters overlay and arms the
   flags in-guest), then launch with the usual command; also arm
   `/tmp/metal-op-timing` **before the game process starts** (third-session instrument).
2. Read `indium-worker-per-frame@` for `binarySemC/frame`, `submitMs/frame`,
   `commits/frame`; read `optime@` for the per-op replay breakdown.
3. If `binarySemC/frame` is small, the lever is inside `replay()` (use `optime@`); if it
   is a few per frame, pool the binary semaphores (flag-gated A/B) and re-measure.
4. Rollback of the overlay: `sh /tmp/opencode/restore-libindium.sh` (or the saved
   `libindium.dylib.darling-lol-backup` next to it).
