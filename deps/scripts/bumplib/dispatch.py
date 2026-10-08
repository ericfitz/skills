"""Resolve axis+name to an adapter module and invoke a verb; handle the 'none' provider."""
import importlib

from . import contracts as c

AXES = {"ecosystem": "ecosystems", "codeHost": "codehosts", "issueTracker": "trackers"}

NONE_RESULTS = {
    "detect": {"present": False},
    "outdated": [],
    "audit": [],
    "alerts": [],
    "prs": c.Context(),
    "issues": c.Context(),
}


def run(axis, name, verb, argv):
    if axis not in AXES:
        raise ValueError(f"unknown axis: {axis}")
    if name == "none":
        if verb not in NONE_RESULTS:
            raise ValueError(f"'none' adapter has no verb '{verb}' on axis {axis}")
        return NONE_RESULTS[verb]
    mod = importlib.import_module(f"bumplib.{AXES[axis]}.{name}")
    return mod.handle(verb, argv)
