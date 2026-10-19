# Riot Vanguard under Darling — analysis

Date: 2026-10-18. Status: **analysis only; nothing here is a workaround.**
This document explains what Vanguard is, what the League client actually does
with it on this machine, why every check fails under Darling, and what that
means for playing. It exists so the failure messages in the logs are not
mistaken for a bug this project can fix.

> **Safety rule.** Vanguard is an anti-cheat. Nothing in this project may spoof
> it, fake its service, patch its libraries, or touch the game process
> (no memory read/write, no injection, no input automation, no
> `SIGSTOP`/`SIGCONT`). The observations below come only from reading Riot's own
> log files and listing filenames.

## TL;DR

- Vanguard is Riot's anti-cheat: a **kernel driver plus a user-mode service** on
  Windows. Riot is bringing it to **macOS** as "Vanguard 2" (user-mode, embedded
  in the client — "without extra installations").
- On this machine the Riot Client and the League client both try to talk to
  Vanguard and both fail cleanly:
  - Riot Client: `vanguard: Failed getting installed version of Vanguard:
    Unsupported operating system` and `vanguard: Failed to get vanguard service
    status: Unimplemented`.
  - League client UI: `Play button disabled … ["Vanguard is not connected or
    enabled"]`, with a dismissible **Vanguard modal**.
- **There is no Vanguard component installed in the Darling prefix at all**
  (no `*vanguard*`, `vgk`, or `vgc` file exists anywhere under `~/.darling`).
  There is nothing to run and nothing the emulated macOS can start.
- The game nevertheless launches and a practice-tool match plays. The check is
  **inert** on this path — which is exactly the risk to be aware of (below).

## What Vanguard is

- Kernel-level anti-cheat by Riot Games. Released 2020 for *VALORANT*; required
  for *League of Legends* on Windows since 11 April 2024.
- On Windows it is two pieces: a **kernel-mode driver** (`vgk.sys`, ring 0) and a
  **user-mode service** (`vgc`) that the client talks to. That split is the
  reason the logs speak of "installed version" and "service status" separately.
- "Vanguard On-Demand" (2026) makes it run only while a game is open, gated on
  the *Pre-Check* machine requirements: Secure Boot, TPM 2.0, IOMMU, VBS and
  HVCI (Windows 11 25H2+).

## Vanguard 2 on macOS

- Riot announced Vanguard is coming to **macOS** for League of Legends, called
  "Vanguard 2", mandatory for LoL on macOS. Press coverage describes it as
  arriving **without extra installations** — i.e. user-mode and embedded in the
  client, not a kext (Apple does not let third parties load kernel extensions the
  way Windows does).
- That matches what the client does here: the macOS League client ships a
  **Riot Client plugin** `rcp-be-lol-vanguard`, and the Riot Client *Foundation*
  library (`libRiotClientFoundation.dylib`) contains the version/service probes.
- The game build's patch metadata is labelled accordingly: the Patchsieve release
  for `lol` on `macos`/`x8664` carries
  `"riot:anticheat_option": ["vanguard"]`.

## What this machine actually does (observed)

All lines below are copy-paste from Riot's own logs on this machine (values
redacted; no account identifiers reproduced).

**Riot Client Foundation —
`~/Library/Logs/Riot Games/Riot Client/Riot Client Logs/*_Riot Client.log`:**

```
000001.481|  ERROR| vanguard: Failed getting installed version of Vanguard: Unsupported operating system
000001.489|  ERROR| vanguard: Failed to get vanguard service status: Unimplemented
000001.488|   OKAY| telemetry: Sending telemetry to schema <…> with: {"errorCode":"","errorDescription":"vanguard: Failed to get vanguard servi…
```

The failure is re-tried through startup (≥10 times) and reported once via
telemetry, then stops.

**League client plugin — `.../LeagueClient Logs/*_LeagueClient.log`:**

```
000012.704| ALWAYS|             Plugin Manager| Initializing plugin rcp-be-lol-vanguard
000012.721| ALWAYS|        rcp-be-lol-vanguard| MvgInit returned 0
000012.727| ALWAYS|        rcp-be-lol-vanguard| BeginVanguardConnect init-status: in-progress ( Enabled VanguardUrl Puuid EnabledMac )
000012.745| ALWAYS|        rcp-be-lol-vanguard| BeginVanguardConnect init-status: in-progress ( Puuid )
000012.764|   OKAY|        rcp-be-lol-vanguard| MvgState: 7
000013.028|   OKAY|        rcp-be-lol-vanguard| Vanguard mailbox notification
000014.698| ALWAYS|        rcp-be-lol-vanguard| BeginVanguardConnect init-status: ready
000014.716|   OKAY|        rcp-be-lol-vanguard| MvgRegisterLogin returned 0
000015.365|   OKAY|        rcp-be-lol-vanguard| MvgState: 0
000304.587|   WARN|        rcp-be-lol-vanguard| Match started without gameId initialized. Not sending MatchStart event to Vanguard.
```

`Mvg*` are the client-side entry points of the Vanguard integration
(`MvgInit`, `MvgRegisterLogin`, `MvgRegisterLogout`, `MvgRA`, `MvgST`). They all
return success; the plugin never reaches a live Vanguard service, so when a match
starts it logs that it is **not** sending the MatchStart event.

**League client UI —
`.../LeagueClient Logs/*_LeagueClientUx.log`:**

```
000024.502|   OKAY|  rcp-fe-ember-libs| reasons.play.disabled, Play button disabled:, detail=["Vanguard is not connected or enabled"]
000025.011|   OKAY|  rcp-fe-lol-navigation| Vanguard Modal region: BR
000034.225|   OKAY|  rcp-fe-lol-navigation| Vanguard Modal vanguardMachineSpecs: {"secureBootEnabled":false,"tpm2Enabled":false}
000034.202|   OKAY|  rcp-fe-lol-navigation| Vanguard Modal systemInfo: {"operatingSystem":{"buildNumber":"","edition":"","platform":"Mac","versionMajor":"14.7","versionMinor":"0"},…
```

The modal reads the machine and sees no Secure Boot and no TPM 2.0 — the same
two facts the Vanguard Pre-Check wants on Windows — and it is told the platform
is "Mac" 14.7 (Darling's reported version).

## Why it fails under Darling

1. **Nothing is installed.** A recursive search of `~/.darling` finds no
   `*vanguard*` and no `vgk`/`vgc` file, in the Riot Client, in the game, or
   anywhere else. macOS Vanguard 2 is "no extra installation" because the real
   macOS client carries the user-mode piece; on Windows the driver is installed
   by the bootstrapper. Under Darling neither exists.
2. **There is no service to connect to.** "Failed to get vanguard service
   status: Unimplemented" is the Foundation asking launchd/Mach for a service
   that Darwin/Darling does not have. "Unsupported operating system" is the
   module refusing to proceed on what it is told the OS is. Whether that is
   Darling's reported build (`14.7`) or a deeper host-OS check is **not**
   determined here, and it does not matter: there is no component to start
   either way.
3. **A kernel component cannot exist here.** The host is Linux; Darling is a
   user-space macOS ABI. Even a real macOS Vanguard has no kext analogue to
   `vgk.sys`, and Darling cannot load kernel extensions from the guest.

**Inference, flagged as such:** the messages are Riot's code correctly reporting
"this platform is not supported by Vanguard", not a Darling bug. There is no
Darling-side defect to fix in `patches/`.

## What it means for playing — the honest risk

- The game **does** run: this machine played a practice-tool match with the modal
  showing, and the working launches of 2026-10-18 (01:41, 12:42, 13:41, 13:50)
  all reached the lobby with Play enabled.
- The check also has a hard-failure mode: some launches instead surface Riot's
  **`VAN -101`** ("unsupported system configuration") and leave Play disabled for
  that session; a restart then usually gets a good one. The client-side plugin's
  undocumented `MvgState` value tracks it (successful sessions log `MvgState: 0`,
  blocked ones `MvgState: 5`), but the meaning is unverified — see
  [troubleshooting](TROUBLESHOOTING.md#client-reports-macos-1010-and-van--101).
- **But the anti-cheat is not running.** Riot's anti-cheat is not enforcing on
  this client, and the Riot Client *knows* it (it logged that the platform is
  unsupported and sent telemetry reporting the failure). Playing in that state is
  outside Riot's supported configuration and carries account risk that is the
  user's to accept, not something this project should try to engineer away.
- **Do not** attempt to satisfy the check — no fake `vgc`/`vgk`, no spoofed
  service status, no patched `libRiotClientFoundation`, no library injection.
  Anything like that is exactly the behaviour an anti-cheat exists to catch.

## How Play comes back (so the modal is not treated as a broken client)

1. The modal appears right after login. In a good launch, dismissing it (and/or
   waiting a few seconds) clears `reasons.play.disabled` and Play re-enables.
2. In a bad launch the client reports `VAN -101` and Play stays disabled for the
   session; restarting the client is the practical remedy.
3. Either way this is **not** a startup bug in Darling to debug — the client is
   faithfully reporting that the platform is unsupported by Vanguard.

## References

- Wikipedia, *Riot Vanguard* (kernel driver on Windows; Vanguard On-Demand and
  its Pre-Check requirements; 2026 HWID notes).
- Riot support, *Riot Vanguard FAQ (League of Legends)*.
- Press reports on Vanguard for macOS ("Vanguard 2 … without extra
  installations").
- Local evidence: the four log excerpts above, plus the Patchsieve manifest label
  and the absence of any `*vanguard*` file under `~/.darling`.
