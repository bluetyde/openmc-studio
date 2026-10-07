"""MCNPy 0.0.7: deck_formatter.line_wrap never returns for a token with no blank that is about as long as the line limit.

MCNP input lines are limited to 128 columns (80 in MCNP5 and early MCNP6), so MCNPy wraps long cards; that is intended.
The bug is what happens when one token (for example a union written without blanks, `(-1000:-1001:...)`) is longer
than the limit: there is no blank to break at, the loop rebuilds the same string forever, memory grows, and the deck
file is left empty. A union of 18 terms (109 characters) wraps; 22 terms (133 characters) hangs.

No Java and no MCNPy gateway is needed: the module is loaded straight from its file, not through the package
(whose __init__ starts the Java server).

    python docs/mcnpy-issues/line_wrap_hang.py                # finds the installed mcnpy
    python docs/mcnpy-issues/line_wrap_hang.py /path/to/mcnpy/deck_formatter.py

Expected on 0.0.7: 10 and 18 terms "returns", 22 and 26 terms "HANGS".
"""
import importlib.util
import os
import subprocess
import sys

LIMIT = 128
TERMS = (10, 18, 22, 26)
TIMEOUT = 5  # seconds


def formatter_path():
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        return sys.argv[1]
    spec = importlib.util.find_spec("mcnpy")  # finds the package without importing it
    if spec is None or not spec.submodule_search_locations:
        sys.exit("mcnpy is not installed; pass the path to its deck_formatter.py")
    return os.path.join(list(spec.submodule_search_locations)[0], "deck_formatter.py")


def one_case(path, n):
    spec = importlib.util.spec_from_file_location("deck_formatter", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    token = "(" + ":".join(str(-(1000 + i)) for i in range(n)) + ")"
    out = mod.line_wrap("5 1 -1.7 " + token, "", LIMIT)
    print(f"{len(token)} {out.count(chr(10)) + 1}")


if __name__ == "__main__":
    if "--case" in sys.argv:
        i = sys.argv.index("--case")
        one_case(sys.argv[i + 1], int(sys.argv[i + 2]))
    else:
        path = formatter_path()
        print(f"{path}, line limit {LIMIT}")
        for n in TERMS:
            try:
                r = subprocess.run([sys.executable, __file__, "--case", path, str(n)], capture_output=True, text=True,
                                   timeout=TIMEOUT)
                width, lines = r.stdout.split()
                print(f"union of {n:2d} terms (token {width} chars): returns, {lines} line(s)")
            except subprocess.TimeoutExpired:
                token = len("(" + ":".join(str(-(1000 + i)) for i in range(n)) + ")")
                print(f"union of {n:2d} terms (token {token} chars): HANGS (no result after {TIMEOUT} s)")
