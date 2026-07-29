"""fxlab -- a small, deliberately boring FX research kit.

It exists to answer one question honestly: does a given rule still make money
after costs, out of sample, on data it has never seen? Everything else is
decoration.
"""

from .engine import Config, run, walk_forward
from .metrics import summary
from .strategies import REGISTRY

__all__ = ["Config", "run", "walk_forward", "summary", "REGISTRY"]
