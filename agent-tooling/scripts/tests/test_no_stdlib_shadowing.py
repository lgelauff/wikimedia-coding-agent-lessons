"""No module in scripts/ may share a name with a stdlib module.

Seven scripts here run `sys.path.insert(0, <scripts dir>)`. Inserting at
position 0 puts this directory ahead of the stdlib for the REST OF THE PROCESS,
not just for the importing module — so a file named e.g. `secrets.py` shadows
the stdlib `secrets` for every later import, including third-party libraries.

That is not hypothetical: `huggingface_hub` does `from secrets import token_hex`
at import time, and a `secrets.py` here broke it with an ImportError that named
huggingface_hub rather than the real cause.

A comment saying "sibling module, not stdlib" is what we had before; it did not
prevent the breakage. This test does.
"""
import pathlib
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent


def test_no_module_shadows_stdlib():
    bad = sorted(
        p.name for p in SCRIPTS_DIR.glob("*.py") if p.stem in sys.stdlib_module_names
    )
    assert not bad, (
        "these modules shadow the stdlib and will break any later import in a "
        f"process that sys.path.insert(0)s this directory: {bad}"
    )
