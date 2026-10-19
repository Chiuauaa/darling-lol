#!/usr/bin/env python3
import riot_build as rb

rb.build_c_probe(
    "riot-local-mutex-check",
    rb.ROOT / "tools/riot-local-mutex-check.c",
    rb.COREVIDEO_FLAGS,
    extra=("-I", str(rb.ELFCALLS), "-O2"),
)
