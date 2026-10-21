"""Where pythia-mongo's commands live and how they are run.

MongoDB takes command documents, not SQL. Every command pythia-mongo sends
is a file in commands/, under the contract the SQL engines keep for their
query files: what it is for, the binds it takes, what it returns, and
nothing else — reviewable in isolation. A bind is written {"$bind": "name"}
where its value goes, so text from a person or an agent always lands as a
value, never as an operator or a command of its own.
"""
import json
import pathlib
import re
import sys

COMMAND_DIR = pathlib.Path(__file__).resolve().parent / "commands"

COMMAND_BINDS = {
    "server-build.json": set(),
    "server-hello.json": set(),
    "collections.json": {"p"},
    "collection.json": {"n"},
    "indexes.json": {"n"},
    "sample.json": {"n", "k"},
    "count.json": {"n"},
    "invalid.json": {"n", "v"},
    "view-run.json": {"n", "k"},
}

# the commands a read runs: never a write, a $out or a $merge (the suite checks)
READ_COMMANDS = frozenset(COMMAND_BINDS)

# commands whose answer is a cursor to read to the end
CURSOR_COMMANDS = ("listCollections", "listIndexes", "aggregate", "find")

_CACHE = {}


def _load(name):
    if name not in _CACHE:
        path = COMMAND_DIR / name
        if name not in COMMAND_BINDS or not path.is_file():
            sys.exit(f"No command file {name} in {COMMAND_DIR}.")
        _CACHE[name] = json.loads(path.read_text(encoding="utf-8"))
    return _CACHE[name]


def placeholders(value):
    """Every bind name a command document uses."""
    if isinstance(value, dict):
        if set(value) == {"$bind"}:
            return {value["$bind"]}
        return set().union(*(placeholders(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(placeholders(v) for v in value)) if value else set()
    return set()


def _fill(value, binds):
    if isinstance(value, dict):
        if set(value) == {"$bind"}:
            return binds[value["$bind"]]
        return {k: _fill(v, binds) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, binds) for v in value]
    return value


def command_of(name, **binds):
    """The command document of one file, its binds in place. A bind the
    file declares and the caller left out, or one it does not declare, is
    refused rather than guessed at."""
    doc = _load(name)
    want = COMMAND_BINDS[name]
    if set(binds) != want:
        gap = sorted(want - set(binds))
        extra = sorted(set(binds) - want)
        sys.exit(f"{name}: " + "; ".join(
            ([f"bind {', '.join(gap)} not given"] if gap else [])
            + ([f"{', '.join(extra)} is not a bind of this command"] if extra else [])))
    return _fill(doc["command"], binds)


def run(conn, name, **binds):
    """The answer to one command file: every document of a cursor, or the
    reply document."""
    command = command_of(name, **binds)
    cursor = next(iter(command)) in CURSOR_COMMANDS
    return conn.run(name, command, cursor, _load(name).get("database") == "admin")


def like_regex(pattern):
    """A LIKE-style pattern (% any run, _ one character) as an anchored,
    case-sensitive regular expression — MongoDB names are case-sensitive."""
    return "^" + "".join(".*" if c == "%" else "." if c == "_" else re.escape(c)
                         for c in str(pattern)) + "$"


def ejson(value, indent=2):
    """value as relaxed Extended JSON: ObjectId, dates and decimals keep
    their type ({"$oid": ...}), plain values read as plain JSON."""
    try:
        from bson import json_util
    except ImportError:                       # the suite runs without the driver
        return json.dumps(value, indent=indent, default=str, ensure_ascii=False)
    return json_util.dumps(value, json_options=json_util.RELAXED_JSON_OPTIONS,
                           indent=indent, ensure_ascii=False)
