"""The `pythia-mongo` command: pythia-core's command line, handed this engine."""
from pythia_core import cli

from .engine import MongoEngine


def main(argv=None):
    return cli.main(MongoEngine(), argv)
