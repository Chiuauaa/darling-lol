#!/usr/bin/env python3
import riot_build as rb

rb.build_c_probe(
    "riot-clock-fastpath-check",
    rb.ROOT / "tools/riot-clock-fastpath-check.c",
    rb.COREVIDEO_FLAGS,
    extra=("-I", str(rb.ELFCALLS), "-O2"),
)
