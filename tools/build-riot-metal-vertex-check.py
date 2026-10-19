#!/usr/bin/env python3
import riot_build as rb

flags = rb.load_flags(rb.METAL_FLAGS, "CXX")
obj = rb.ROOT / "build/riot-metal-vertex-check.o"
rb.compile_object("clang++", flags, "CXX",
                  rb.ROOT / "tools/riot-metal-vertex-check.mm", obj, extra=("-O2",))
rb.link_probe("clang++", (obj,), rb.ROOT / "build/riot-metal-vertex-check",
              libraries=("-lSystem", "-lc++", "-lobjc"), frameworks=("Foundation",),
              extra=(rb.ROOT / "build/riot-Metal",))
