#!/usr/bin/env python3
import riot_build as rb

rb.build_c_probe(
    "riot-local-region-check",
    rb.ROOT / "tools/riot-local-region-check.c",
    rb.COREVIDEO_FLAGS,
    extra=("-I", str(rb.ELFCALLS), "-O2"),
)
