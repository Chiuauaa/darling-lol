#!/usr/bin/env python3
import riot_build as rb

rb.build_c_probe(
    "riot-region-count19-check",
    rb.ROOT / "tools/riot-region-count19-check.c",
    rb.COREVIDEO_FLAGS,
    extra=("-I", str(rb.ELFCALLS), "-O2"),
)
