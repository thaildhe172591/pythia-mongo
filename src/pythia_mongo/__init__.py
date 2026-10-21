"""pythia for MongoDB: database development for AI agents, over pythia-core.
Alpha — see README.md for what works today."""
__version__ = "0.1.1"     # kept equal to pyproject.toml (tests/test_mongo.py)

from .engine import MongoEngine  # noqa: E402,F401 — needs __version__ first
