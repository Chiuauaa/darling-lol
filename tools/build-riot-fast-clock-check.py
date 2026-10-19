#!/usr/bin/env python3
import riot_build as rb

rb.build_c_probe(
    "riot-fast-clock-check",
    rb.ROOT / "tools/riot-fast-clock-check.c",
    rb.COREVIDEO_FLAGS,
    extra=("-I", str(rb.ELFCALLS), "-O2"),
)
