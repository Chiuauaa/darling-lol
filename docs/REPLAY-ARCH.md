# Replay architecture: plan to cut submissions per frame

Status: **proposal, nothing implemented.** Written by the coordinator session after the
runtime analysis (`ses_eab36ec62…`), the telemetry/bench data and the API reference in
[GRAPHICS-STACK.md](GRAPHICS-STACK.md) were cross-checked. It changes no patch, no
overlay and no game-start policy; it is the plan the implementer-of-record executes.

Scope: this is a **Darling** tree — it translates **macOS** APIs. The stack in play is
Mach-O (`mldr`/`wrapgen`) → `Metal.framework` → **Indium (Metal → Vulkan)** → host Vulkan,
plus `OpenGL.framework` → CGL → host EGL for the present path. Nothing here is a Windows
or D3D path; the Wine/Proton layers in `GRAPHICS-STACK.md` are reference analogues for
how a translation layer behaves, not components of this tree.

Goal: **60 FPS** in the same scene, without hardware changes.

## 1. Measured baseline

All numbers come from archived traces (`build/fps-diag/match2-metal-trace.log`,
`thread-prof.log`) and the runtime sessions; sources are in
[WORKLOG-FPS-2026-10-18.md](WORKLOG-FPS-2026-10-18.md) and
[COORDINATION.md](COORDINATION.md).

| Quantity | Value |
|---|---|
| FPS | 27.8 (p50 28) |
| Frame time | ~36 ms |
| `commits/frame` | 23.9 |
| `submitMs/frame` (replay worker) | 25.4 ms |
| `drain@commit` on the main thread | 58 % of its wall |
| Replay worker CPU | 0.52–0.71 core, ~0.55 of it **sys** |
| Involuntary context switches | 1100–2300/s |
| `vkQueueSubmit2` per frame | ~1, cost ≈ 0 ms |
| GPU | 1–30 %, P5, ~885–1126 MHz, 15–40 W |
| Render passes per frame | ≈ commits (`encCreate ≈ 0.92 × commits`) |

Derived throughput: **ceiling ≈ 664 commits/s = FPS × commits/frame**. The frame is
produced by a single ordered replay worker; the GPU is the victim, not the cause.

## 2. Where the requirement lands

60 FPS at 23.9 commits/frame needs ~1434 commits/s, i.e. **2.16× the current ceiling**.
There are only two ways to get there:

- **fewer, larger replay units**: `commits/frame ≤ 11` at today's ceiling, or
- **a cheaper commit**: raise the ceiling by ~2.2× (same code, less kernel time).

Both are architectural. Neither is reachable by trimming a fixed per-commit cost by a
few tens of percent.

## 3. Already ruled out (do not re-propose)

- **Framebuffer cache.** Measured on driver 580: `vkCreateFramebuffer` +
  `vkDestroyFramebuffer` = 0.10 µs wall / 0.06 µs CPU per pair → **~2.6 µs/frame** at
  ~26 passes. Three orders of magnitude below the budget.
- **Parallel replay.** The game uses 0.94 core; the box sits at ~3.7 of 4 threads
  (Riot client Chromium helpers ~1.7 core, `darlingserver` ~0.3, desktop ~0.3). Free
  headroom **~0.25 core**: a second replay worker does not fit, and the main thread
  blocked in `drain@commit` is *blocked*, not idle-CPU — it frees nothing.
- **Present path and driver submit.** ~6 ms/frame present, `vkQueueSubmit2` ≈ 0,
  `nextDrawableWait` ≈ 0.
- **Vsync cap.** FPS falls well below 60 as the scene fills.
- **Micro-optimising the fixed per-commit cost** (scratch vectors, casts, timer poll).
  Worth tens of percent at best, and currently suspected of causing the black screen
  (see §6, gate 0).

## 4. The open question that gates the design

Per commit the worker spends roughly `0.55 × 36 ms / 23.9 ≈ 0.8 ms` in **kernel time**,
while the one queue submission per frame costs ~0 ms. That is the red flag: something
per commit is entering the kernel hundreds of times more expensively than the submit
itself. Until it is attributed, choosing between §5-A and §5-B is guesswork.

Candidates, all reachable with existing instruments:

1. driver entries per commit — `vkEndCommandBuffer`, pipeline barriers, memory binding;
2. binary semaphore create/destroy/wait — the only one with a counter today
   (`binarySemMs`, ~0.054 core);
3. `graphicsQueueMutex` contention between the worker and the producer, consistent with
   1100–2300 involuntary switches/s;
4. a per-commit darlingserver/Mach RPC or an event-loop wake that crosses the emulation
   boundary.

**Experiment (gate 1):** one match with only `/tmp/metal-debug-timing`, `phases@`
sections armed, plus per-frame counters for submits, barriers, semaphore operations,
mutex acquisitions and context switches. One knob per game start.

## 5. Workstreams

**A. Fewer replay units (target 22 → ≤11 per frame).**
The translator already emits ~one render pass per command buffer. Two sub-questions, in
order: (i) how many *adjacent* passes share attachments and have no read-after-write
hazard, i.e. how many are mergeable at all — measurable from a trace, no code; (ii) what
makes a pass split today (encoder boundaries, load/store ops, a barrier the translator
inserts on its own). Deliverable: a hazard rule plus a mergeable-pass count. Only then
write the merge, as the smallest measurable step.

**B. Cheaper commit (raise the ceiling).**
- collapse per-commit synchronization into **timeline semaphores** (counter waits): Indium
  already requires Vulkan 1.3 / timeline semaphores, and `MTLSharedEvent` maps onto them.
  A binary semaphore created and destroyed per commit is the model to retire;
- one queue submission per frame (or a small fixed number) instead of ~1 per commit path;
- remove per-commit locking/spinning that shows up as involuntary context switches.

**C. Reclaim host CPU (policy, not code, and only after A and B).**
~1.7 core sits in the Riot client's Chromium helpers. Whether they are needed while a
match runs is analyzable read-only; any actual intervention (priority, cgroup) is a
decision for the user, never something a session does on its own.

## 6. Order and gates

0. **Bisect closed.** The black screen / `sig=6` regression lives in the 5th/6th indium
   hunks — the same code workstream B rewrites. Nothing in §5 starts before this.
1. `phases@` attribution capture (§4). Decides between A and B, or both.
2. Designs: mergeable-pass count and hazard rule (A); timeline-semaphore and
   single-submit mapping for the present boundary (B).
3. Implement the smallest measurable step of the chosen workstream, as its own commit,
   with `prepare.py --check-only` clean.
4. A/B measurement in the same scene: FPS, `commits/frame`, `submitMs/frame`, GPU clocks.
5. Only then §5-C.

## 7. Success criteria

- same scene, FPS ≥ 55–60 (or a documented ceiling measurement explaining the remainder);
- `commits/frame ≤ 11`, or ceiling ≥ ~1400 commits/s, or a documented combination;
- no new `Metal Device timed out`, no black screen, no drawable starvation;
- `prepare.py --check-only` clean and one knob per game start maintained throughout.

## 8. Evidence discipline

Every claim above is trace- or bench-backed; where a number is missing (the §4
attribution, the mergeable-pass count) the plan says so and schedules the measurement
instead of guessing. This file is updated with results, not rewritten from memory.
