#!/usr/bin/env python3
"""pythia-mongo's suite: no database, no pymongo. A fake connection answers
each command file by name, the way the SQL engines' suites answer query
files.

Needs pythia-core importable: installed, or a checkout next to this one
(../pythia-core), or PYTHIA_CORE_SRC pointing at its src/.

Run: python tests/test_mongo.py
"""
import contextlib
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
try:
    import pythia_core  # noqa: F401
except ModuleNotFoundError:
    for candidate in (os.environ.get("PYTHIA_CORE_SRC"),
                      ROOT.parent / "pythia-core" / "src"):
        if candidate and pathlib.Path(candidate).is_dir():
            sys.path.insert(1, str(candidate))
            break

from pythia_core.engine import engine_problems  # noqa: E402

import pythia_mongo  # noqa: E402
from pythia_mongo import catalog, cli, read  # noqa: E402
from pythia_mongo.engine import MongoEngine  # noqa: E402


def expect_exit(fn, *needles):
    try:
        fn()
    except SystemExit as e:
        text = str(e.code)
        for n in needles:
            assert n.lower() in text.lower(), f"missing {n!r} in: {text}"
        return text
    raise AssertionError("expected SystemExit")


# --- packaging -------------------------------------------------------------------------

def pyproject():
    return (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_version_matches_pyproject():
    m = re.search(r'^version = "([^"]+)"', pyproject(), re.M)
    assert m and m.group(1) == pythia_mongo.__version__


def test_dependencies_are_core_and_the_driver_only():
    m = re.search(r"^dependencies = \[(.*?)\]", pyproject(), re.M | re.S)
    names = [re.split(r"[<>=!~ ]", d.strip().strip('"'))[0]
             for d in m.group(1).split(",") if d.strip()]
    assert names == ["pythia-core", "pymongo"], names


def test_console_script_is_pythia_mongo():
    assert 'pythia-mongo = "pythia_mongo.cli:main"' in pyproject()
    assert '"commands/*.json"' in pyproject()


def test_engine_answers_the_connect_and_read_tiers():
    assert engine_problems(MongoEngine(), tiers=("connect", "read")) == []


# --- the command contract: every command a file, every bind a value -------------------

JAVASCRIPT = ("$where", "$function", "$accumulator", "mapReduce", "$eval", "eval")
WRITES = ("insert", "update", "delete", "findAndModify", "create", "drop",
          "collMod", "createIndexes", "dropIndexes", "dropDatabase", "renameCollection",
          "createUser", "dropUser", "grantRolesToUser", "$out", "$merge")


def keys_of(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from keys_of(v)
    elif isinstance(value, list):
        for v in value:
            yield from keys_of(v)


def test_every_command_is_a_reviewable_file():
    files = sorted(p.name for p in catalog.COMMAND_DIR.glob("*.json"))
    assert files == sorted(catalog.COMMAND_BINDS), \
        (set(files) ^ set(catalog.COMMAND_BINDS))
    for name in files:
        doc = json.loads((catalog.COMMAND_DIR / name).read_text(encoding="utf-8"))
        assert set(doc) - {"database"} == {"purpose", "binds", "returns", "command"}, name
        assert all(str(doc[k]).strip() for k in ("purpose", "returns")), name
        assert set(doc["binds"]) == catalog.COMMAND_BINDS[name], name
        assert catalog.placeholders(doc["command"]) == catalog.COMMAND_BINDS[name], name
        keys = set(keys_of(doc["command"]))
        assert not keys & set(JAVASCRIPT), (name, keys & set(JAVASCRIPT))
        if name in catalog.READ_COMMANDS:
            assert not keys & set(WRITES), (name, keys & set(WRITES))


def test_a_bind_lands_as_a_value_and_must_be_declared():
    cmd = catalog.command_of("collection.json", n='t_order"; {"$where": "1"}')
    assert cmd == {"listCollections": 1, "filter": {"name": 't_order"; {"$where": "1"}'},
                   "nameOnly": False}
    expect_exit(lambda: catalog.command_of("collection.json"), "collection.json", "n")
    expect_exit(lambda: catalog.command_of("collection.json", n="x", extra=1),
                "collection.json", "extra")
    expect_exit(lambda: catalog.command_of("nope.json"), "nope.json")


def test_a_like_pattern_becomes_an_anchored_regex():
    r = catalog.like_regex
    assert r("t_order%") == "^t.order.*$"
    assert r("v.paid") == r"^v\.paid$"
    assert r("%") == "^.*$"
    assert re.fullmatch(r("T(x)%"), "T(x)y") and not re.fullmatch(r("t%"), "T1")


# --- the connection --------------------------------------------------------------------

class DriverError(Exception):
    pass


class OperationFailure(DriverError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code, self.details = code, {"errmsg": message, "code": code}


class ServerSelectionTimeoutError(DriverError):
    pass


@contextlib.contextmanager
def fake_pymongo(fail=None):
    """pymongo as far as connect() uses it; every client it built is kept."""
    made = []

    class Admin:
        def command(self, name):
            if fail:
                raise fail
            return {"ok": 1}

    class Client:
        def __init__(self, *args, **kw):
            self.args, self.kw, self.closed = args, kw, False
            self.admin = Admin()
            made.append(self)

        def __getitem__(self, name):
            return types.SimpleNamespace(name=name, client=self)

        def close(self):
            self.closed = True

    errors = types.ModuleType("pymongo.errors")
    errors.PyMongoError, errors.OperationFailure = DriverError, OperationFailure
    errors.ServerSelectionTimeoutError = ServerSelectionTimeoutError
    errors.ConfigurationError = type("ConfigurationError", (DriverError,), {})
    mod = types.ModuleType("pymongo")
    mod.MongoClient, mod.errors = Client, errors
    keep = {k: sys.modules.get(k) for k in ("pymongo", "pymongo.errors")}
    sys.modules["pymongo"], sys.modules["pymongo.errors"] = mod, errors
    try:
        yield made
    finally:
        for k, v in keep.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


DEV = {"host": "db-dev", "database": "app", "user": "app_agent", "password": "s3cret"}


def test_connect_passes_exactly_the_settings():
    with fake_pymongo() as made:
        conn = MongoEngine().connect(dict(DEV))
        conn2 = MongoEngine().connect(dict(DEV, port=27018, auth_source="app", tls=True,
                                           replica_set="rs0", direct=True))
    first, second = made
    assert first.args == ("db-dev",) and first.kw == {
        "port": 27017, "username": "app_agent", "password": "s3cret",
        "authSource": "admin", "tls": False, "appname": "pythia-mongo",
        "serverSelectionTimeoutMS": 10000, "connectTimeoutMS": 10000}, first.kw
    assert second.kw["port"] == 27018 and second.kw["authSource"] == "app"
    assert second.kw["tls"] is True and second.kw["replicaSet"] == "rs0"
    assert second.kw["directConnection"] is True
    assert conn.db.name == "app" and conn2.db.name == "app"
    MongoEngine().close(conn)
    assert first.closed
    with fake_pymongo() as made:
        MongoEngine().connect({"host": "db", "database": "app"})
    assert "username" not in made[0].kw and "password" not in made[0].kw


def test_connect_fails_at_once_on_a_server_that_does_not_answer():
    # a MongoClient connects lazily: connect() pings, so the failure is named here
    with fake_pymongo(fail=ServerSelectionTimeoutError("db-dev:27017: timed out")) as made:
        try:
            MongoEngine().connect(dict(DEV))
        except ServerSelectionTimeoutError:
            pass
        else:
            raise AssertionError("connect() returned a client nothing answered")
    assert made[0].closed


def test_connect_refuses_a_half_filled_or_unknown_setting_before_the_driver():
    with fake_pymongo() as made:
        expect_exit(lambda: MongoEngine().connect({"host": "db"}),
                    "missing 'database'", ".pythia/mongo/connections.json")
        expect_exit(lambda: MongoEngine().connect(dict(DEV, tls="yes")),
                    '"tls" must be true or false')
        expect_exit(lambda: MongoEngine().connect(dict(DEV, uri="mongodb://u:p@h/app")),
                    '"uri"', "password")
    assert made == []


def test_missing_driver_names_the_package():
    keep = sys.modules.get("pymongo")
    sys.modules["pymongo"] = None
    try:
        expect_exit(lambda: MongoEngine().driver_errors(), "pip install pymongo")
    finally:
        if keep is None:
            sys.modules.pop("pymongo", None)
        else:
            sys.modules["pymongo"] = keep


def test_connect_failure_names_the_next_step():
    e = MongoEngine()
    m = e.connect_failure(OperationFailure("Authentication failed.", 18), "dev", DEV)
    assert "Authentication failed" in m and "app_agent" in m and "auth_source" in m
    m = e.connect_failure(ServerSelectionTimeoutError("db-dev:27017: timed out"), "dev", DEV)
    assert "Nothing answered at db-dev:27017/app" in m and '"direct": true' in m
    m = e.connect_failure(ServerSelectionTimeoutError("SSL handshake failed: x"), "dev", DEV)
    assert "TLS" in m and '"tls"' in m
    m = e.connect_failure(DriverError("something else"), "dev", DEV)
    assert "something else" in m and "--conn" in m


def test_target_never_shows_the_password():
    e = MongoEngine()
    assert e.target_of(DEV) == "db-dev:27017/app"
    assert e.target_of(dict(DEV, host="a:1,b:2")) == "a:1,b:2/app"
    assert "s3cret" not in e.target_of(DEV)
    assert e.schema_of(DEV) == "app" and e.schema_of(dict(DEV, database="App")) == "App"


def test_example_config_resolves_and_holds_no_secret():
    example = json.loads((ROOT / "examples" / "connections.example.json")
                         .read_text(encoding="utf-8"))
    entry = example[example["default"]]
    assert {"host", "port", "database", "user", "password"} <= set(entry)
    assert entry["password"] == "" and "uri" not in entry


# --- the read tier, against a fake connection -----------------------------------------

class FakeConn:
    """Answers each command file by name; an unscripted file is a KeyError."""

    def __init__(self, answers, database="app"):
        self.answers, self.asked = answers, []
        self.db = types.SimpleNamespace(name=database)

    def run(self, name, command, cursor, admin):
        self.asked.append((name, command))
        answer = self.answers[name]
        return answer(command) if callable(answer) else answer

    def names(self):
        return [n for n, _ in self.asked]


VALIDATOR = {"$jsonSchema": {"bsonType": "object", "required": ["status", "total"],
                             "properties": {
                                 "status": {"enum": ["DRAFT", "PAID"],
                                            "description": "DRAFT until paid"},
                                 "total": {"bsonType": ["int", "double"], "minimum": 0}}}}
T_ORDER = {"name": "t_order", "type": "collection",
           "options": {"validator": VALIDATOR, "validationLevel": "strict",
                       "validationAction": "error"}}
T_LINE = {"name": "t_order_line", "type": "collection",
          "options": {"validator": {"order_id": {"$exists": True}},
                      "validationLevel": "moderate", "validationAction": "warn"}}
T_CUSTOMER = {"name": "t_customer", "type": "collection", "options": {}}
V_PAID = {"name": "v_paid", "type": "view",
          "options": {"viewOn": "t_order", "pipeline": [{"$match": {"status": "PAID"}}]}}
V_LINES = {"name": "v_order_lines", "type": "view",
           "options": {"viewOn": "t_order", "pipeline": [
               {"$lookup": {"from": "t_order_line", "localField": "_id",
                            "foreignField": "order_id", "as": "lines"}},
               {"$unionWith": {"coll": "t_customer", "pipeline": [
                   {"$lookup": {"from": "t_note", "pipeline": [], "as": "n"}}]}}]}}
V_BIG = {"name": "v_paid_big", "type": "view",
         "options": {"viewOn": "v_paid", "pipeline": [{"$match": {"total": {"$gt": 15}}}]}}
V_GHOST = {"name": "v_ghost", "type": "view",
           "options": {"viewOn": "t_missing", "pipeline": []}}
ALL = [T_CUSTOMER, T_ORDER, T_LINE, V_GHOST, V_LINES, V_PAID, V_BIG]


def listing(*objs):
    """collections.json / collection.json answered from these objects."""
    def answer(command):
        name = command["filter"].get("name")
        if isinstance(name, str):
            return [o for o in objs if o["name"] == name]
        rx = command["filter"]["$and"][0]["name"]["$regex"]
        return [o for o in objs if re.fullmatch(rx.strip("^$"), o["name"])]
    return answer


def conn_with(**extra):
    return FakeConn({"collections.json": listing(*ALL), "collection.json": listing(*ALL),
                     **extra})


def test_ls_lists_collections_and_views_by_pattern():
    conn = conn_with()
    cols, rows = read.object_names(conn, "app", "t_%", 50)
    assert cols == ["NAME", "TYPE", "DETAIL"]
    assert rows == [("t_customer", "COLLECTION", ""),
                    ("t_order", "COLLECTION", "validator (strict, error)"),
                    ("t_order_line", "COLLECTION", "validator (moderate, warn)")], rows
    _, rows = read.object_names(conn, "app", "v%", 2)
    assert rows == [("v_ghost", "VIEW", "on t_missing, 0 stages"),
                    ("v_order_lines", "VIEW", "on t_order, 2 stages")], rows
    flt = conn.asked[0][1]["filter"]["$and"]
    assert flt[0] == {"name": {"$regex": "^t..*$"}}
    assert flt[1] == {"name": {"$not": {"$regex": r"^system\."}}}


def test_src_prints_a_validator_or_a_pipeline_as_extended_json():
    conn = conn_with()
    rows = read.source(conn, "app", "t_order")
    assert rows[0] == ("t_order", 1, "{")
    text = "\n".join(t for _, _, t in rows)
    assert json.loads(text) == {"validator": VALIDATOR, "validationLevel": "strict",
                                "validationAction": "error"}
    assert [n for _, n, _ in rows] == list(range(1, len(rows) + 1))
    view = "\n".join(t for _, _, t in read.source(conn, "app", "v_paid"))
    assert json.loads(view) == {"viewOn": "t_order", "pipeline": [{"$match": {"status": "PAID"}}]}
    assert read.source(conn, "app", "t_customer") == []        # no validator: no code
    assert read.source(conn, "app", "nope") == []


def test_cols_reads_a_sample_and_says_so():
    docs = [{"_id": 1, "status": "DRAFT", "total": 10, "address": {"city": "Hue"}},
            {"_id": 2, "status": "PAID", "total": 20.5, "tags": ["a", "b"]},
            {"_id": 3, "status": "PAID", "total": None}]
    conn = conn_with(**{"sample.json": docs, "count.json": {"n": 3, "ok": 1}})
    cols, rows, blind = read.columns(conn, "app", "t_order")
    assert cols == ["FIELD", "TYPES", "SEEN", "REQUIRED", "COMMENT"]
    got = {r[0]: r[1:] for r in rows}
    # a sample comes back in random order: fields by path (_id first), types
    # by how many documents hold them, so the answer reads the same each time
    assert [r[0] for r in rows] == ["_id", "address", "address.city", "status", "tags",
                                    "tags[]", "total"], rows
    assert got["status"] == ("string", "3 of 3", "yes", "DRAFT until paid")
    assert got["total"] == ("double, int, null", "3 of 3", "yes", "")
    _, again, _ = read.columns(conn_with(**{"sample.json": docs[::-1],
                                            "count.json": {"n": 3, "ok": 1}}), "app", "t_order")
    assert again == rows                                   # the same, whatever the order
    _, mostly, _ = read.columns(conn_with(**{"sample.json": docs + [{"_id": 4, "total": 7}],
                                             "count.json": {"n": 4, "ok": 1}}), "app", "t_order")
    assert dict((r[0], r[1]) for r in mostly)["total"] == "int, double, null"
    assert got["address.city"] == ("string", "1 of 3", "", "")
    assert got["tags[]"] == ("string", "1 of 3", "", "")
    assert blind is None                            # fewer than asked for: all read
    sample = next(c for n, c in conn.asked if n == "sample.json")
    assert sample["aggregate"] == "t_order" and sample["pipeline"][0]["$sample"]["size"] == read.SAMPLE
    many = conn_with(**{"sample.json": docs * 400, "count.json": {"n": 90000, "ok": 1}})
    _, _, blind = read.columns(many, "app", "t_order")
    assert blind and "1200 sampled documents" in blind and "90000" in blind
    assert read.columns(conn_with(), "app", "nope") is None


def test_cols_names_a_declared_field_no_document_holds():
    conn = conn_with(**{"sample.json": [{"_id": 1, "status": "DRAFT"}],
                        "count.json": {"n": 1, "ok": 1}})
    _, rows, _ = read.columns(conn, "app", "t_order")
    total = next(r for r in rows if r[0] == "total")
    assert total[1:4] == ("", "0 of 1", "yes"), total


def test_ddl_rebuilds_the_commands_that_make_it():
    idx = [{"v": 2, "key": {"_id": 1}, "name": "_id_"},
           {"v": 2, "key": {"status": 1}, "name": "ix_order_status"},
           {"v": 2, "key": {"ref": 1}, "name": "ux_order_ref", "unique": True,
            "partialFilterExpression": {"ref": {"$exists": True}}}]
    conn = conn_with(**{"indexes.json": idx})
    doc = json.loads(read.ddl(conn, "app", "t_order"))
    assert doc == [{"create": "t_order", "validator": VALIDATOR, "validationLevel": "strict",
                    "validationAction": "error"},
                   {"createIndexes": "t_order", "indexes": [
                       {"key": {"status": 1}, "name": "ix_order_status"},
                       {"key": {"ref": 1}, "name": "ux_order_ref", "unique": True,
                        "partialFilterExpression": {"ref": {"$exists": True}}}]}], doc
    view = json.loads(read.ddl(conn, "app", "v_paid"))
    assert view == [{"create": "v_paid", "viewOn": "t_order",
                     "pipeline": [{"$match": {"status": "PAID"}}]}]
    bare = json.loads(read.ddl(conn_with(**{"indexes.json": idx[:1]}), "app", "t_customer"))
    assert bare == [{"create": "t_customer"}]
    assert read.ddl(conn, "app", "nope") == ""


def test_grep_searches_validators_and_pipelines():
    conn = conn_with()
    cols, rows = read.grep(conn, "app", "paid", 50)
    assert cols == ["NAME", "TYPE", "LINE", "TEXT"]
    names = [(r[0], r[1]) for r in rows]
    assert ("t_order", "COLLECTION") in names and ("v_paid", "VIEW") in names
    assert all("paid" in r[3].lower() for r in rows)
    _, few = read.grep(conn, "app", "paid", 1)
    assert len(few) == 1


def test_impact_walks_views_and_names_what_it_cannot_see():
    conn = conn_with()
    rows, blind = read.dependents(conn, "app", "t_order", 2)
    assert rows == [(1, "app", "v_order_lines", "VIEW", "catalog"),
                    (1, "app", "v_paid", "VIEW", "catalog"),
                    (2, "app", "v_paid_big", "VIEW", "catalog")], rows
    assert any("application code" in b for b in blind)
    rows, _ = read.dependents(conn, "app", "t_note", 1)      # inside a nested pipeline
    assert rows == [(1, "app", "v_order_lines", "VIEW", "catalog")], rows
    assert read.dependents(conn, "app", "nope", 1) is None
    rows, blind = read.dependencies(conn, "app", "v_order_lines", 1)
    assert [(r[2], r[3]) for r in rows] == [("t_order", "COLLECTION"),
                                           ("t_order_line", "COLLECTION"),
                                           ("t_customer", "COLLECTION"),
                                           ("t_note", "MISSING")], rows
    rows, _ = read.dependencies(conn, "app", "v_paid_big", 2)
    assert [(r[0], r[2]) for r in rows] == [(1, "v_paid"), (2, "t_order")], rows
    rows, _ = read.dependencies(conn, "app", "t_order", 2)
    assert rows == []


def test_a_pipeline_is_read_for_every_collection_it_reads():
    assert read.references([
        {"$match": {"from": "not_a_stage"}},
        {"$lookup": {"from": "t_line", "as": "l", "pipeline": [
            {"$lookup": {"from": "t_sku", "pipeline": [], "as": "s"}}]}},
        {"$graphLookup": {"from": "t_tree", "startWith": "$p", "connectFromField": "p",
                          "connectToField": "_id", "as": "t"}},
        {"$unionWith": "t_old"},
        {"$facet": {"a": [{"$lookup": {"from": "t_tag", "as": "x", "pipeline": []}}],
                    "b": [{"$unionWith": {"coll": "t_more"}}]}}]) == [
        "t_line", "t_sku", "t_tree", "t_old", "t_tag", "t_more"]


def test_errors_count_what_breaks_the_validator_and_run_each_view():
    def invalid(command):
        n = {"t_order": 0, "t_order_line": 2}[command["aggregate"]]
        return [{"n": [{"n": n}] if n else [], "first": [{"_id": 7}, {"_id": 9}][:n]}]

    def run_view(command):
        if command["aggregate"] == "v_order_lines":
            raise OperationFailure("Failed to parse number 'DRAFT' in $convert", 241)
        return [{"n": 1}]
    conn = conn_with(**{"invalid.json": invalid, "view-run.json": run_view})
    rows, blind = read.compile_errors(conn, "app", None, DriverError)
    assert rows == [
        ("t_order_line", "COLLECTION", None, None, "warning",
         "2 documents fail the validator (moderate, warn) — first _id: 7, 9"),
        ("v_ghost", "VIEW", None, None, "error", "reads what does not exist: t_missing"),
        ("v_order_lines", "VIEW", None, None, "error",
         "241: Failed to parse number 'DRAFT' in $convert"),
        ("v_order_lines", "VIEW", None, None, "error", "reads what does not exist: t_note"),
    ], rows
    assert "t_customer" in blind and "no validator" in blind
    assert f"first {read.VIEW_PROBE}" in blind
    rows, blind = read.compile_errors(conn, "app", "t_order", DriverError)
    assert rows == [] and blind is None                       # every document counted
    rows, blind = read.compile_errors(conn, "app", "t_customer", DriverError)
    assert rows == [] and "no validator" in blind
    assert read.compile_errors(conn, "app", "nope", DriverError) is None


def test_check_end_to_end():
    build = {"version": "7.0.45", "ok": 1}
    hello = {"setName": "rs0", "isWritablePrimary": True, "ok": 1}
    conn = FakeConn({"server-build.json": build, "server-hello.json": hello})
    e = MongoEngine()
    assert e.server_version(conn) == "MongoDB 7.0.45 (replica set rs0, primary) — database app"
    conn.answers["server-hello.json"] = {"isWritablePrimary": True, "ok": 1}
    assert "(standalone)" in e.server_version(conn)
    conn.answers["server-hello.json"] = {"setName": "rs0", "isWritablePrimary": False,
                                         "secondary": True, "ok": 1}
    assert "secondary" in e.server_version(conn)
    conn.answers["server-hello.json"] = {"msg": "isdbgrid", "isWritablePrimary": True, "ok": 1}
    assert "mongos" in e.server_version(conn)
    assert e.current_schema(conn) == "app"


def test_another_tools_config_is_not_ours():
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / ".pythia" / "postgres").mkdir(parents=True)
        (root / ".pythia" / "postgres" / "connections.json").write_text(
            json.dumps({"dev": {"host": "h", "dbname": "d"}}), encoding="utf-8")
        (root / ".pythia" / "connections.json").write_text("{}", encoding="utf-8")
        keep = os.getcwd()
        os.chdir(td)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                try:
                    cli.main(["connections"])
                except SystemExit as e:
                    out.write(str(e.code))
            assert ".pythia/mongo/connections.json" in out.getvalue()
        finally:
            os.chdir(keep)


# --- Phase 5b: the write tier ---------------------------------------------------------

from pythia_mongo import write  # noqa: E402


def doc(**kw):
    return json.dumps(kw)


def classified(text):
    return write.classify(text)[0]


def refusal(text):
    group, why = write.classify(text)
    assert group is None, (text, group)
    return why


def test_classify_sorts_every_command_or_says_why_not():
    assert classified('{"insert": "t_order", "documents": [{"_id": 9, "status": "DRAFT", "total": 1}]}') == "data_dml"
    assert classified(doc(update="t_order", updates=[{"q": {"status": "DRAFT"},
                                                       "u": {"$set": {"total": 0}}, "multi": True}])) == "data_dml"
    assert classified(doc(update="t_order", updates=[{"q": {"_id": 1},
                                                       "u": {"$set": {"total": 0}}}])) == "data_dml"
    assert classified(doc(delete="t_order", deletes=[{"q": {"status": "X"}, "limit": 0}])) == "data_dml"
    assert classified(doc(delete="t_order", deletes=[{"q": {"_id": 3}, "limit": 1}])) == "data_dml"
    assert classified(doc(create="v_x", viewOn="t_order", pipeline=[])) == "source"
    assert classified(doc(create="t_new", validator={"a": {"$exists": True}})) == "structural"
    assert classified(doc(collMod="t_order", validator={"a": {"$exists": True}})) == "source"
    assert classified(doc(collMod="t_order", validationLevel="moderate")) == "source"
    assert classified(doc(collMod="v_paid", viewOn="t_order", pipeline=[])) == "source"
    assert classified(doc(collMod="t_order", index={"name": "ix_order_status", "hidden": True})) == "structural"
    assert classified(doc(createIndexes="t_order", indexes=[{"key": {"ref": 1}, "name": "ix_ref"}])) == "structural"
    assert classified(doc(dropIndexes="t_order", index="ix_ref")) == "structural"
    assert classified(doc(drop="t_order")) == "structural"
    for text, needle in (
            ("{ not json", "Extended JSON"),
            ("db.t_order.insertOne({status: 'DRAFT'})", "mongosh"),
            ('[{"drop": "a"}, {"drop": "b"}]', "one command"),
            ('{"drop": "a", "drop": "b"}', "twice"),
            ("{}", "no command"),
            (doc(delete="t", deletes=[{"q": {"$where": "this.a > 1"}, "limit": 0}]), "JavaScript"),
            (doc(insert="t", documents=[{"f": {"$code": "function () {}"}}]), "JavaScript"),
            (doc(create="v", viewOn="t", pipeline=[{"$group": {"_id": 1, "x": {"$accumulator": {}}}}]), "JavaScript"),
            (doc(create="v", viewOn="t", pipeline=[{"$out": "t_copy"}]), "$out"),
            (doc(collMod="v", viewOn="t", pipeline=[{"$merge": {"into": "t2"}}]), "$merge"),
            (doc(aggregate="t", pipeline=[], cursor={}), "reads"),
            (doc(find="t", filter={}), "reads"),
            (doc(findAndModify="t", query={}, remove=True), "findAndModify"),
            (doc(createUser="u", pwd="x", roles=[]), "DBA"),
            (doc(grantRolesToUser="u", roles=["root"]), "DBA"),
            (doc(renameCollection="app.t", to="app.u"), "renameCollection"),
            (doc(dropDatabase=1), "dropDatabase"),
            (doc(insert="t", documents=[{}], bypassDocumentValidation=True), "validator"),
            (doc(insert="t", documents=[{}], writeConcern={"w": 0}), "transaction"),
            (doc(insert="t", documents=[{}], lsid={"id": 1}), "transaction"),
            (doc(insert="t", documents=[]), "no document"),
            (doc(update="t", updates=[{"q": {"a": 1}, "u": {"$set": {"b": 1}}, "upsert": True,
                                        "multi": True}]), "upsert"),
            (doc(update="t", updates=[{"q": {"a": 1}, "u": {"$set": {"b": 1}}}]), "multi"),
            (doc(delete="t", deletes=[{"q": {"a": 1}, "limit": 1}]), "limit"),
            (doc(update="t", updates=[{"q": {"_id": 1}, "u": {}}, {"q": {"_id": 2}, "u": {}}]), "one per file"),
            (doc(insert="system.views", documents=[{}]), "system"),
            (doc(insert=5, documents=[{}]), "collection"),
            (doc(collMod="t", validator={}, index={"name": "i", "hidden": True}), "one change"),
            (doc(collMod="v", pipeline=[]), "viewOn"),
            (doc(compact="t"), "Cannot classify")):
        assert needle.lower() in refusal(text).lower(), (text, refusal(text))


def test_parse_object_names_what_a_definition_change_changes():
    p = write.parse_object
    assert p(doc(collMod="t_order", validator={}), "source") == \
        {"type": "VALIDATOR", "name": "t_order", "schema": None}
    assert p(doc(create="v_x", viewOn="t", pipeline=[]), "source") == \
        {"type": "VIEW", "name": "v_x", "schema": None}
    assert p(doc(collMod="v_x", viewOn="t", pipeline=[]), "source")["type"] == "VIEW"
    assert p(doc(drop="t"), "structural") is None


def test_prepare_statement_is_canonical_json():
    a = write.prepare_statement('{"drop":"t_order"}', "structural")
    b = write.prepare_statement('{ "drop" : "t_order" }\n', "structural")
    assert a == b and json.loads(a) == {"drop": "t_order"}


def test_destruction_is_named():
    d = write.destructive_reason
    assert "every document" in d(doc(drop="t_order"), "structural")
    assert "scan" in d(doc(dropIndexes="t_order", index="ix_ref"), "structural")
    assert "every index" in d(doc(dropIndexes="t_order", index="*"), "structural")
    assert "every document" in d(doc(delete="t", deletes=[{"q": {}, "limit": 0}]), "data_dml")
    assert "every document" in d(doc(update="t", updates=[{"q": {}, "u": {"$set": {"a": 1}},
                                                            "multi": True}]), "data_dml")
    assert d(doc(delete="t", deletes=[{"q": {"a": 1}, "limit": 0}]), "data_dml") is None
    assert d(doc(insert="t", documents=[{}]), "data_dml") is None
    assert d(doc(createIndexes="t", indexes=[{"key": {"a": 1}, "name": "i"}]), "structural") is None


def test_dml_probe_reads_the_filter():
    assert write.dml_probe(doc(update="t_order", updates=[
        {"q": {"status": "DRAFT"}, "u": {"$set": {"total": 0}}, "multi": True}])) == \
        ("t_order", {"status": "DRAFT"})
    assert write.dml_probe(doc(delete="t_order", deletes=[{"q": {"_id": 3}, "limit": 1}])) == \
        ("t_order", {"_id": 3})
    assert write.dml_probe(doc(insert="t_order", documents=[{}])) is None


def test_a_snapshot_is_the_definition_of_the_right_kind_or_nothing():
    conn = conn_with()
    view = {"type": "VIEW", "name": "v_paid", "schema": None}
    snap = write.snapshot(conn, "app", "source", view)
    assert json.loads(snap["v_paid"]) == {"viewOn": "t_order",
                                          "pipeline": [{"$match": {"status": "PAID"}}]}
    val = {"type": "VALIDATOR", "name": "t_order", "schema": None}
    assert json.loads(write.snapshot(conn, "app", "source", val)["t_order"]) == {
        "validator": VALIDATOR, "validationLevel": "strict", "validationAction": "error"}
    plain = {"type": "VALIDATOR", "name": "t_customer", "schema": None}
    assert json.loads(write.snapshot(conn, "app", "source", plain)["t_customer"]) == {
        "validator": {}, "validationLevel": "strict", "validationAction": "error"}
    # a name that holds another kind of object is no snapshot of this one
    assert write.snapshot(conn, "app", "source", dict(view, name="t_order")) == {}
    assert write.snapshot(conn, "app", "source", dict(val, name="v_paid")) == {}
    assert write.snapshot(conn, "app", "source", dict(view, name="v_new")) == {}
    assert write.snapshot(conn, "app", "structural", None) == {}


def test_restore_puts_back_the_definition_or_drops():
    r = write.restore_statement
    val = {"type": "VALIDATOR", "name": "t_order", "schema": None}
    before = json.dumps({"validator": {"a": {"$exists": True}}, "validationLevel": "strict",
                         "validationAction": "error"})
    text = r("source", val, before, {})
    assert json.loads(text) == {"collMod": "t_order", "validator": {"a": {"$exists": True}},
                                "validationLevel": "strict", "validationAction": "error"}
    assert classified(text) == "source"
    view = {"type": "VIEW", "name": "v_paid", "schema": None}
    text = r("source", view, json.dumps({"viewOn": "t_order", "pipeline": [{"$match": {}}]}), {})
    assert json.loads(text) == {"collMod": "v_paid", "viewOn": "t_order",
                                "pipeline": [{"$match": {}}]}
    text = r("source", view, "", {})
    assert json.loads(text) == {"drop": "v_paid"} and classified(text) == "structural"


class WriteConn(FakeConn):
    """FakeConn plus statements, run inside a transaction or not."""

    def __init__(self, answers, replica_set=True, reply=None):
        hello = {"setName": "rs0", "isWritablePrimary": True} if replica_set else \
            {"isWritablePrimary": True}
        super().__init__({"server-hello.json": hello, "collections.json": listing(*ALL),
                          "collection.json": listing(*ALL), **answers})
        self.reply, self.statements, self.began = reply or {"n": 1, "ok": 1}, [], 0

    def run_statement(self, command, in_txn):
        self.statements.append((command, in_txn))
        self.began += bool(in_txn)
        reply = self.reply
        return reply(command) if callable(reply) else reply


def rehearse(conn, text, group=None):
    group = group or write.classify(text)[0]
    stmt = write.prepare_statement(text, group)
    ident = write.parse_object(stmt, group)
    snap = write.snapshot(conn, "app", group, ident) if ident else {}
    return write.rehearse(conn, "app", group, stmt, ident, snap, DriverError)


UPDATE = doc(update="t_order", updates=[{"q": {"status": "DRAFT"}, "u": {"$set": {"total": 0}},
                                         "multi": True}])


def test_data_is_rehearsed_in_a_transaction_on_a_replica_set_only():
    out = rehearse(WriteConn({}, replica_set=False), UPDATE)
    assert "replica set" in out["error"] and "standalone" in out["error"]
    conn = WriteConn({}, reply={"n": 2, "nModified": 2, "ok": 1})
    out = rehearse(conn, UPDATE)
    assert out["error"] is None and out["rows"] == 2 and not out.get("predicted")
    assert conn.statements == [(json.loads(UPDATE), True)]
    conn = WriteConn({}, reply={"n": 0, "ok": 1, "writeErrors": [
        {"index": 0, "code": 121, "errmsg": "Document failed validation"}]})
    out = rehearse(conn, doc(insert="t_order", documents=[{"_id": 9}]))
    assert out["error"] == "121: Document failed validation", out
    conn = WriteConn({}, reply={"n": 1, "ok": 1, "writeConcernError": {"code": 64, "errmsg": "w"}})
    assert "64" in rehearse(conn, UPDATE)["error"]


def failing(n, ids=(7, 9)):
    return lambda c: [{"n": [{"n": n}] if n else [], "first": [{"_id": i} for i in ids[:n]]}]


NEW_V = {"$jsonSchema": {"required": ["status", "total", "created"]}}


def test_a_validator_change_is_predicted_by_counting_what_it_would_reject():
    conn = WriteConn({"invalid.json": failing(2)})
    out = rehearse(conn, doc(collMod="t_order", validator=NEW_V))
    assert out["predicted"] is True and out["error"] is None and conn.statements == []
    assert out["broken"] == [("t_order", "COLLECTION", "2 documents fail the new validator "
                              "(strict, error) — first _id: 7, 9")], out["broken"]
    asked = [c for n, c in conn.asked if n == "invalid.json"][-1]
    assert asked["pipeline"][0] == {"$match": {"$nor": [NEW_V]}}
    assert json.loads(out["after"]) == {"validator": NEW_V, "validationLevel": "strict",
                                        "validationAction": "error"}
    assert out["verified"] is True
    out = rehearse(WriteConn({"invalid.json": failing(0)}), doc(collMod="t_order", validator=NEW_V))
    assert out["broken"] == [] and out["predicted"]

    def bad(c):
        raise OperationFailure("unknown top level operator: $foo", 2)
    out = rehearse(WriteConn({"invalid.json": bad}), doc(collMod="t_order", validator={"$foo": 1}))
    assert out["predicted"] and "would refuse" in out["error"] and "$foo" in out["error"]
    out = rehearse(WriteConn({}), doc(collMod="t_nope", validator=NEW_V))
    assert "no collection named t_nope" in out["error"]
    out = rehearse(WriteConn({}), doc(collMod="v_paid", validator=NEW_V))
    assert "view" in out["error"]


def test_a_view_is_predicted_by_running_its_pipeline():
    seen = []

    def run(command):
        seen.append(command)
        if any("$toInt" in json.dumps(s) for s in command["pipeline"]) and \
                not command["pipeline"][0].get("$match", {}).get("_id"):
            raise OperationFailure("Failed to parse number 'DRAFT'", 241)
        return [{"n": 3}]
    conn = WriteConn({"pipeline-run.json": run})
    out = rehearse(conn, doc(create="v_int", viewOn="t_order",
                             pipeline=[{"$project": {"n": {"$toInt": "$status"}}}]))
    assert out["predicted"] and out["error"] is None and conn.statements == []
    assert out["own_errors"] == [("v_int", "VIEW", f"fails over its first {write.PROBE} "
                                  "documents: 241: Failed to parse number 'DRAFT'")]
    assert seen[0]["aggregate"] == "t_order"
    assert seen[0]["pipeline"][0] == {"$match": {"_id": {"$exists": False}}}   # parse only
    assert out["verified"] is False and f"first {write.PROBE}" in out["blind"]

    def parse_error(command):
        raise OperationFailure("Unrecognized pipeline stage name: '$nope'", 40324)
    out = rehearse(WriteConn({"pipeline-run.json": parse_error}),
                   doc(create="v_bad", viewOn="t_order", pipeline=[{"$nope": {}}]))
    assert "would refuse" in out["error"] and "$nope" in out["error"]
    ok = lambda c: [{"n": 1}]          # noqa: E731
    out = rehearse(WriteConn({"pipeline-run.json": ok}),
                   doc(create="v_x", viewOn="t_gone", pipeline=[]))
    assert out["own_errors"] == [("v_x", "VIEW", "reads what does not exist: t_gone")]
    assert "exists" in rehearse(WriteConn({"pipeline-run.json": ok}),
                                doc(create="v_paid", viewOn="t_order", pipeline=[]))["error"]
    assert "exists" in rehearse(WriteConn({"pipeline-run.json": ok}),
                                doc(create="t_order", viewOn="t_line", pipeline=[]))["error"]
    assert "no view named" in rehearse(WriteConn({"pipeline-run.json": ok}),
                                       doc(collMod="v_nope", viewOn="t", pipeline=[]))["error"]


def test_a_view_change_runs_the_views_built_on_it():
    def run(command):
        if command["aggregate"] == "t_order" and {"$match": {"total": {"$gt": 15}}} in command["pipeline"] \
                and {"$project": {"total": 0}} in command["pipeline"]:
            raise OperationFailure("$gt needs a total", 2)
        return [{"n": 1}]
    conn = WriteConn({"pipeline-run.json": run})
    out = rehearse(conn, doc(collMod="v_paid", viewOn="t_order",
                             pipeline=[{"$match": {"status": "PAID"}}, {"$project": {"total": 0}}]))
    assert out["broken"] == [("v_paid_big", "VIEW", f"fails over its first {write.PROBE} "
                              "documents: 2: $gt needs a total")], out
    composed = [c for n, c in conn.asked if n == "pipeline-run.json"][-1]["pipeline"]
    assert composed[:3] == [{"$match": {"status": "PAID"}}, {"$project": {"total": 0}},
                            {"$match": {"total": {"$gt": 15}}}], composed


def test_a_unique_index_is_predicted_by_looking_for_duplicates():
    conn = WriteConn({"indexes.json": [{"v": 2, "key": {"_id": 1}, "name": "_id_"}],
                      "duplicates.json": [{"_id": {"ref": "A-1"}, "n": 2}]})
    out = rehearse(conn, doc(createIndexes="t_order", indexes=[
        {"key": {"ref": 1}, "name": "ux_ref", "unique": True,
         "partialFilterExpression": {"status": "PAID"}}]))
    assert out["predicted"] and "duplicate" in out["error"] and "A-1" in out["error"], out
    asked = [c for n, c in conn.asked if n == "duplicates.json"][-1]
    assert asked["pipeline"][0] == {"$match": {"status": "PAID"}}
    assert asked["pipeline"][1]["$group"]["_id"] == {"ref": "$ref"}
    conn = WriteConn({"indexes.json": [], "duplicates.json": []})
    out = rehearse(conn, doc(createIndexes="t_order", indexes=[
        {"key": {"ref": 1, "status": 1}, "name": "ux_rs", "unique": True, "sparse": True}]))
    assert out["error"] is None and out["predicted"]
    asked = [c for n, c in conn.asked if n == "duplicates.json"][-1]
    assert asked["pipeline"][0] == {"$match": {"$or": [{"ref": {"$exists": True}},
                                                      {"status": {"$exists": True}}]}}
    conn = WriteConn({"indexes.json": [{"key": {"x": 1}, "name": "ix_ref"}]})
    out = rehearse(conn, doc(createIndexes="t_order", indexes=[{"key": {"ref": 1}, "name": "ix_ref"}]))
    assert "ix_ref" in out["error"] and "exists" in out["error"]
    assert "duplicates.json" not in conn.names()
    conn = WriteConn({"indexes.json": [{"key": {"ref": 1}, "name": "ix_ref"}]})
    assert "no index named" in rehearse(conn, doc(dropIndexes="t_order", index="nope"))["error"]
    assert rehearse(conn, doc(dropIndexes="t_order", index="ix_ref"))["error"] is None


def test_a_drop_is_predicted_by_what_reads_it():
    out = rehearse(WriteConn({}), doc(drop="t_order"))
    assert out["predicted"] and ("v_order_lines", "VIEW", "reads what will not exist: t_order") \
        in out["broken"], out
    assert "no collection or view named" in rehearse(WriteConn({}), doc(drop="t_nope"))["error"]
    assert rehearse(WriteConn({}), doc(create="t_new"))["error"] is None
    assert "exists" in rehearse(WriteConn({}), doc(create="t_order"))["error"]


class AutoReconnect(DriverError):
    pass


class WriteConcernError(OperationFailure):
    pass


def test_execute_runs_once_and_says_whether_it_landed():
    stmt = write.prepare_statement(doc(drop="t_x"), "structural")
    conn = WriteConn({}, reply={"ok": 1})
    assert write.execute(conn, "app", "structural", stmt, None) == {}
    assert conn.statements == [({"drop": "t_x"}, False)]

    def refuse(c):
        raise OperationFailure("E11000 duplicate key error", 11000)
    assert write.execute(WriteConn({}, reply=refuse), "app", "structural", stmt, None) == \
        {"error": "11000: E11000 duplicate key error"}

    def drop(c):
        raise AutoReconnect("connection reset by peer")
    out = write.execute(WriteConn({}, reply=drop), "app", "structural", stmt, None)
    assert out["escaped"] and "connection reset" in out["error"]

    def concern(c):
        raise WriteConcernError("waiting for replication timed out", 64)
    assert write.execute(WriteConn({}, reply=concern), "app", "structural", stmt, None)["escaped"]
    out = write.execute(WriteConn({}, reply={"ok": 1, "writeConcernError": {"code": 64, "errmsg": "w"}}),
                        "app", "structural", stmt, None)
    assert out["escaped"]


def test_what_landed_is_read_back_against_the_prediction():
    ident = {"type": "VALIDATOR", "name": "t_order", "schema": None}
    stmt = write.prepare_statement(doc(collMod="t_order", validator=NEW_V), "source")
    predicted = {"predicted": True, "broken": [("t_order", "COLLECTION", "x")], "own_errors": [],
                 "prediction": {"failing": 2}}
    after = dict(T_ORDER, options={"validator": NEW_V, "validationLevel": "strict",
                                   "validationAction": "error"})
    conn = WriteConn({"collection.json": listing(after, *ALL[2:]), "invalid.json": failing(3)})
    found = write.verify_written(conn, "app", "source", stmt, ident, predicted)
    assert found["differs"] == ["3 documents fail the validator now; the prediction said 2"]
    assert len(found["broken"]) == 1
    conn = WriteConn({"collection.json": listing(after, *ALL[2:]), "invalid.json": failing(2)})
    assert write.verify_written(conn, "app", "source", stmt, ident, predicted)["differs"] == []
    conn = WriteConn({"collection.json": listing(T_ORDER), "invalid.json": failing(2)})
    assert "reads back" in write.verify_written(conn, "app", "source", stmt, ident,
                                                predicted)["differs"][0]
    istmt = write.prepare_statement(doc(createIndexes="t_order", indexes=[
        {"key": {"ref": 1}, "name": "ix_ref"}]), "structural")
    conn = WriteConn({"indexes.json": []})
    assert "ix_ref" in write.verify_written(conn, "app", "structural", istmt, None,
                                            {"predicted": True})["differs"][0]


def test_rows_are_measured_and_fingerprinted():
    conn = WriteConn({"probe.json": [{"_id": None, "n": 2, "h": "12345"}],
                      "probe-sample.json": [{"_id": 1, "status": "DRAFT"}, {"_id": 2, "status": "DRAFT"}]})
    got = write.measure_row_set(conn, "t_order", {"status": "DRAFT"})
    assert (got["count"], got["hash"], got["columns"]) == (2, "12345", ["DOCUMENT"])
    assert got["predicate"] == '{"status": "DRAFT"}' and got["truncated"] is False
    assert json.loads(got["sample"][0][0]) == {"_id": 1, "status": "DRAFT"}
    asked = [c for n, c in conn.asked if n == "probe.json"][-1]
    assert asked["pipeline"][0] == {"$match": {"status": "DRAFT"}}
    empty = WriteConn({"probe.json": [], "probe-sample.json": []})
    assert write.measure_row_set(empty, "t_order", {"x": 1})["count"] == 0


def test_a_user_that_can_do_far_more_is_named():
    def power(*roles):
        return write.privilege_warning(FakeConn({"connection-status.json": {"authInfo": {
            "authenticatedUsers": [{"user": "app_agent", "db": "admin"}],
            "authenticatedUserRoles": [{"role": r, "db": "admin"} for r in roles]}}}), "app")
    assert "root" in power("root") and "app_agent" in power("root")
    assert "dbOwner" in power("dbOwner", "read")
    assert power("readWrite") is None


def test_the_engine_answers_the_write_and_predict_tiers():
    assert engine_problems(MongoEngine(), tiers=("connect", "read", "write", "predict")) == []
    from pythia_core import policy
    notes = MongoEngine.rollback_notes
    assert set(notes) == set(policy.GROUPS) and all(notes.values())


def main():
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except (Exception, SystemExit) as e:  # noqa: BLE001 — keep going
                failed += 1
                print(f"FAIL {name}: {e!r}")
    if failed:
        sys.exit(f"{failed} test(s) failed")
    print("OK")


if __name__ == "__main__":
    main()
