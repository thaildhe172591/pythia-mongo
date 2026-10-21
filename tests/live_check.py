#!/usr/bin/env python3
"""pythia-mongo against a real MongoDB — a disposable one only.

1. Always (when PYTHIA_MONGO_LIVE_HOST is set): connect and `check`.
2. With PYTHIA_MONGO_LIVE_DISPOSABLE=1 only: the database pythia_live is
   dropped and rebuilt from tests/fixtures/app_owner.json, a user
   pythia_agent is made (the `read` role on it), and every read command
   runs through the command line as that user.
3. Then the fixture is loaded again, the user may write (readWrite and
   dbAdmin), and every write path runs through the gate: a validator
   predicted, approved, written and restored, and one whose prediction
   moved; views; indexes, a unique one refused for its duplicates; data
   rehearsed in a transaction, rows that move; a release of data through
   `deploy`, landed whole or not at all; a lint finding in a real preview;
   a write under an autopilot lease; a drop that breaks a view.

Never point this at a shared server: it creates a user and drops a
database. Skipped unless PYTHIA_MONGO_LIVE_HOST is set:

    PYTHIA_MONGO_LIVE_HOST=127.0.0.1 PYTHIA_MONGO_LIVE_PORT=27017 \\
    PYTHIA_MONGO_LIVE_USER=root PYTHIA_MONGO_LIVE_PASSWORD=... \\
    PYTHIA_MONGO_LIVE_DISPOSABLE=1 python tests/live_check.py

PYTHIA_MONGO_LIVE_DIRECT=1 connects to the one member named, not the
replica set it advertises (a container reached through a mapped port).
"""
import contextlib
import io
import json
import os
import pathlib
import secrets
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
for candidate in (os.environ.get("PYTHIA_CORE_SRC"), ROOT.parent / "pythia-core" / "src"):
    if candidate and pathlib.Path(candidate).is_dir():
        sys.path.insert(1, str(candidate))
        break

DB = "pythia_live"
AGENT = "pythia_agent"


def ok(what):
    print(f"PASS {what}")


def admin_entry():
    env = os.environ
    entry = {"host": env["PYTHIA_MONGO_LIVE_HOST"],
             "port": int(env.get("PYTHIA_MONGO_LIVE_PORT") or 27017),
             "user": env.get("PYTHIA_MONGO_LIVE_USER") or "root",
             "password": env["PYTHIA_MONGO_LIVE_PASSWORD"], "auth_source": "admin"}
    if env.get("PYTHIA_MONGO_LIVE_DIRECT") == "1":
        entry["direct"] = True
    return entry


@contextlib.contextmanager
def admin(entry):
    import pymongo
    client = pymongo.MongoClient(entry["host"], port=entry["port"], username=entry["user"],
                                 password=entry["password"], authSource="admin",
                                 directConnection=bool(entry.get("direct")))
    try:
        yield client
    finally:
        client.close()


def run_commands(entry, commands):
    with admin(entry) as client:
        for cmd in commands:
            client[DB].command(cmd)


def fixture():
    from bson import json_util
    return json_util.loads((ROOT / "tests" / "fixtures" / "app_owner.json")
                           .read_text(encoding="utf-8"))


class Project:
    """A project folder whose connection is the agent user: the journal and
    the grants outlive a single command."""

    def __init__(self, entry):
        self.td = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.td.name)
        self.state = state = self.root / ".pythia" / "mongo"
        state.mkdir(parents=True)
        path = state / "connections.json"
        path.write_text(json.dumps({"live": entry}), encoding="utf-8")
        if os.name == "posix":
            os.chmod(path, 0o600)

    def run(self, *argv):
        """(exit code, stdout, the refusal message or '')"""
        from pythia_mongo import cli
        keep = os.getcwd()
        os.chdir(self.root)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                code, why = cli.main(list(argv)) or 0, ""
        except SystemExit as e:
            code, why = (e.code, "") if isinstance(e.code, int) else (1, str(e))
        finally:
            os.chdir(keep)
        return code, out.getvalue(), why

    def json(self, *argv):
        code, out, why = self.run(*argv, "--json")
        assert code == 0, (argv, why, out)
        return json.loads(out.strip().splitlines()[-1])

    def file(self, name, value):
        text = value if isinstance(value, str) else json.dumps(value, indent=2)
        (self.root / name).write_text(text, encoding="utf-8")
        return name

    def preview(self, name, value):
        return self.json("apply", self.file(name, value))

    def approve(self, token):
        """The developer's own act, at their own console."""
        from pythia_core import human
        human.FORCE_CONSOLE = True
        try:
            code, _, why = self.run("approve", token)
            assert code == 0, why
        finally:
            human.FORCE_CONSOLE = False

    def confirm(self, *argv):
        """(exit code, the last JSON line or None, the refusal)"""
        code, out, why = self.run(*argv, "--json")
        lines = out.strip().splitlines()
        return code, (json.loads(lines[-1]) if lines and lines[-1].startswith("{")
                      else None), why

    def policy(self, **groups):
        (self.state / "policy.json").write_text(json.dumps(groups), encoding="utf-8")


def check_connect(entry):
    p = Project(dict(entry, database="admin"))
    doc = p.json("check")
    server = {r["ITEM"]: r["VALUE"] for r in doc["rows"]}["server"]
    assert server.startswith("MongoDB ") and "database admin" in server, server
    assert doc["below_floor"] is None, doc["below_floor"]    # CI runs 7.0 and 8.0
    ok(f"check: {server}, at or above the floor")
    return server


def load_fixture(entry):
    with admin(entry) as client:
        client.drop_database(DB)
        if client[DB].command("usersInfo", AGENT)["users"]:
            client[DB].command("dropUser", AGENT)
    run_commands(entry, fixture())
    password = "Agent#" + secrets.token_hex(8)
    with admin(entry) as client:
        client[DB].command("createUser", AGENT, pwd=password,
                           roles=[{"role": "read", "db": DB}])
    agent = {k: v for k, v in entry.items() if k in ("host", "port", "direct")}
    agent.update(database=DB, user=AGENT, password=password, auth_source=DB)
    return agent


def check_reads(agent):
    p = Project(agent)
    doc = p.json("check")
    assert doc["schema_drift"] is False, doc
    ok("check: the agent user names its database")

    rows = p.json("ls", "t_%")["rows"]
    assert [(r["NAME"], r["DETAIL"]) for r in rows] == [
        ("t_customer", ""), ("t_order", "validator (strict, error)"),
        ("t_order_line", "validator (moderate, warn)")], rows
    names = [r["NAME"] for r in p.json("ls", "%")["rows"]]
    assert "system.views" not in names and "v_paid" in names, names
    ok("ls: collections and views by LIKE pattern, system collections left out")

    text = "\n".join(r["TEXT"] for r in p.json("src", "t_order")["rows"])
    assert json.loads(text)["validator"]["$jsonSchema"]["required"] == ["status", "total"]
    text = "\n".join(r["TEXT"] for r in p.json("src", "v_paid")["rows"])
    assert json.loads(text) == {"viewOn": "t_order", "pipeline": [{"$match": {"status": "PAID"}}]}
    ok("src: a validator and a view's pipeline as Extended JSON")

    doc = p.json("cols", "t_order")
    cols = {r["FIELD"]: r for r in doc["rows"]}
    assert cols["status"]["REQUIRED"] == "yes" and cols["status"]["COMMENT"] == "DRAFT until paid"
    assert cols["total"]["TYPES"] == "int, double" and cols["created"]["TYPES"] == "date", cols
    assert cols["ref"]["SEEN"] == "2 of 3" and doc["blind_spot"] is None, doc
    cust = {r["FIELD"]: r for r in p.json("cols", "t_customer")["rows"]}
    assert cust["_id"]["TYPES"] == "objectId" and cust["address.city"]["SEEN"] == "1 of 2"
    assert cust["tags[]"]["TYPES"] == "string", cust
    ok("cols: fields, types and how many documents hold each, from a sample")

    hits = {(r["NAME"], r["TYPE"]) for r in p.json("grep", "PAID")["rows"]}
    assert {("t_order", "COLLECTION"), ("v_paid", "VIEW")} <= hits, hits
    ok("grep: every validator and pipeline line holding a text")

    deps = [(r["NAME"], r["TYPE"]) for r in p.json("deps", "v_order_lines")["rows"]]
    assert deps == [("t_order", "COLLECTION"), ("t_order_line", "COLLECTION")], deps
    doc = p.json("impact", "t_order", "--depth", "2")
    found = [(r["LEVEL"], r["NAME"]) for r in doc["rows"]]
    assert found == [(1, "v_order_lines"), (1, "v_paid"), (2, "v_paid_big"),
                     (1, "v_status_int")], found
    assert any("application code" in b for b in doc["blind_spots"]), doc
    ok("deps and impact: views read what they read, and the application is named "
       "as unseen")

    doc = p.json("errors")
    got = {(r["NAME"], r["SEVERITY"], r["MESSAGE"].split(":")[0]) for r in doc["rows"]}
    assert ("t_order_line", "warning",
            "1 document fails the validator (moderate, warn) — first _id") in got, got
    assert ("v_ghost", "error", "reads what does not exist") in got, got
    assert any(n == "v_status_int" and s == "error" for n, s, _ in got), got
    assert "t_customer" in doc["blind_spot"], doc
    doc = p.json("errors", "t_order")
    assert doc["rows"] == [] and doc["verified"] is True, doc
    ok("errors: documents a validator rejects, views that fail or read nothing")
    return p


def ddl_round_trip(entry, p):
    from bson import json_util
    for name in ("t_order", "v_paid"):
        before = p.json("ddl", name)["rows"][0]["DDL"]
        with admin(entry) as client:
            client[DB].drop_collection(name)
        run_commands(entry, json_util.loads(before))
        after = p.json("ddl", name)["rows"][0]["DDL"]
        assert after == before, (name, before, after)
    ok("ddl round trip: drop, run the rebuilt commands, rebuild — identical")


def options(entry, name):
    with admin(entry) as client:
        found = list(client[DB].list_collections(filter={"name": name}))
        return found[0]["options"] if found else None


def indexes(entry, name):
    with admin(entry) as client:
        return [ix["name"] for ix in client[DB][name].list_indexes()]


def check_writes(entry):
    from pythia_core import human
    human.FORCE_CONSOLE = False             # no person here unless one approves
    agent = load_fixture(entry)
    with admin(entry) as client:
        client[DB].command("grantRolesToUser", AGENT, roles=[
            {"role": "readWrite", "db": DB}, {"role": "dbAdmin", "db": DB}])
    p = Project(agent)
    try:
        _validators(entry, p)
        _views(entry, p)
        _indexes(entry, p)
        _data(entry, p)
        _release(entry, p)
        _lint(entry, p)
        _lease(entry, p)
        _drop(entry, p)
    finally:
        human.FORCE_CONSOLE = None


STRICTER = {"collMod": "t_order", "validator": {"$jsonSchema": {
    "bsonType": "object", "required": ["status", "total", "ref"],
    "properties": {"status": {"enum": ["DRAFT", "PAID"]}}}}}


def _validators(entry, p):
    original = options(entry, "t_order")["validator"]
    doc = p.preview("stricter.json", STRICTER)
    reh = doc["rehearsal"]
    assert reh["predicted"] is True and doc["object"] == "t_order", doc
    assert reh["broken"] == [["t_order", "COLLECTION", "1 document fails the new validator "
                              "(strict, error) — first _id: 3"]], reh
    assert options(entry, "t_order")["validator"] == original     # nothing ran
    code, out, _ = p.run("apply", "stricter.json")
    assert "predicted — nothing ran" in out and "ran and rolled back" not in out, out
    ok("a validator change is predicted — nothing runs, the documents it would "
       "reject are counted")

    p.approve(doc["token"])
    with admin(entry) as client:          # a document arrives that the new one rejects
        client[DB]["t_order"].insert_one({"_id": 4, "status": "DRAFT", "total": 1})
    code, _, why = p.confirm("apply", "stricter.json", "--confirm", doc["token"])
    assert code == 1 and "prediction moved" in why, why
    assert options(entry, "t_order")["validator"] == original
    ok("a prediction that moved after approval writes nothing")

    doc = p.preview("stricter.json", STRICTER)
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "stricter.json", "--confirm", doc["token"])
    assert code == 3 and res["predicted"] and res["differs"] == [], (code, why, res)
    assert [b[0] for b in res["broken"]] == ["t_order"], res
    assert options(entry, "t_order")["validator"] == STRICTER["validator"]
    ok("approved, written once, read back: the breakage the developer saw lands, exit 3")

    eid = res["restore"].split()[-1]
    doc = p.json("journal", "restore", eid)
    assert doc["rehearsal"]["predicted"] is True, doc
    p.approve(doc["token"])
    code, res, why = p.confirm("journal", "restore", eid, "--confirm", doc["token"])
    assert code == 0 and res["differs"] == [], (code, why, res)
    assert options(entry, "t_order")["validator"] == original
    with admin(entry) as client:
        client[DB]["t_order"].delete_one({"_id": 4})
    ok("journal restore: the old validator, predicted, approved and put back")


def _views(entry, p):
    view = {"create": "v_total_int", "viewOn": "t_order",
            "pipeline": [{"$project": {"n": {"$toInt": "$status"}}}]}
    doc = p.preview("view.json", view)
    reh = doc["rehearsal"]
    assert reh["predicted"] and reh["own_errors"][0][0] == "v_total_int", reh
    assert "fails over its first 100 documents" in reh["own_errors"][0][2], reh
    assert reh["verified"] is False and options(entry, "v_total_int") is None
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "view.json", "--confirm", doc["token"])
    assert code == 3 and options(entry, "v_total_int")["viewOn"] == "t_order", (code, why, res)
    ok("a view is predicted by running its pipeline; an approved failure lands, exit 3")

    p.policy(structural="confirm")
    eid = res["restore"].split()[-1]
    doc = p.json("journal", "restore", eid)
    p.approve(doc["token"])
    code, res, why = p.confirm("journal", "restore", eid, "--confirm", doc["token"])
    assert code == 0 and options(entry, "v_total_int") is None, (code, why, res)
    ok("a new view's undo is a drop, approved like any write")

    code, _, why = p.run("apply", p.file("bad.json", {"create": "v_bad", "viewOn": "t_order",
                                                      "pipeline": [{"$nope": {}}]}))
    assert code == 1 and "Prediction failed" in why and "$nope" in why, why
    code, _, why = p.run("apply", p.file("out.json", {"create": "v_out", "viewOn": "t_order",
                                                      "pipeline": [{"$out": "t_copy"}]}))
    assert code == 1 and "$out" in why and options(entry, "t_copy") is None, why
    ok("a pipeline MongoDB would refuse, or one that writes, has nothing to approve")


def _indexes(entry, p):
    code, _, why = p.run("apply", p.file("ux.json", {"createIndexes": "t_order", "indexes": [
        {"key": {"status": 1}, "name": "ux_status", "unique": True}]}))
    assert code == 1 and "duplicate" in why and "PAID" in why, why
    assert "ux_status" not in indexes(entry, "t_order")
    ok("a unique index that would meet duplicates is refused by its prediction")

    doc = p.preview("ix.json", {"createIndexes": "t_order", "indexes": [
        {"key": {"total": -1}, "name": "ix_order_total"}]})
    assert doc["rehearsal"]["predicted"] and "ix_order_total" not in indexes(entry, "t_order")
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "ix.json", "--confirm", doc["token"])
    assert code == 0 and res["differs"] == [], (code, why, res)
    assert "ix_order_total" in indexes(entry, "t_order")
    doc = p.preview("dx.json", {"dropIndexes": "t_order", "index": "ix_order_total"})
    assert "scan" in doc["destructive"], doc
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "dx.json", "--confirm", doc["token"])
    assert code == 0 and "ix_order_total" not in indexes(entry, "t_order"), (code, why, res)
    ok("an index is predicted, built once and read back; dropping one says what it costs")


def _data(entry, p):
    p.policy(structural="confirm", data_dml="confirm")
    raise_draft = {"update": "t_order", "updates": [
        {"q": {"status": "DRAFT"}, "u": {"$inc": {"total": 1}}, "multi": True}]}
    doc = p.preview("raise.json", raise_draft)
    assert doc["rehearsal"]["predicted"] is False and doc["rehearsal"]["rows"] == 1, doc
    assert doc["row_set"]["count"] == 1 and '"DRAFT"' in doc["row_set"]["predicate"], doc
    with admin(entry) as client:
        total = client[DB]["t_order"].find_one({"_id": 1})["total"]
    assert total == 10                                       # rolled back
    p.approve(doc["token"])
    with admin(entry) as client:          # the row moves after approval
        client[DB]["t_order"].update_one({"_id": 1}, {"$set": {"total": 11}})
    code, _, why = p.confirm("apply", "raise.json", "--confirm", doc["token"])
    assert code == 1, why
    doc = p.preview("raise.json", raise_draft)
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "raise.json", "--confirm", doc["token"])
    assert code == 0 and res["rows"] == 1, (code, why, res)
    with admin(entry) as client:
        assert client[DB]["t_order"].find_one({"_id": 1})["total"] == 12
    ok("data is rehearsed in a transaction: approved on its documents, refused when "
       "they move, then written")

    code, _, why = p.run("apply", p.file("bad.json", {"insert": "t_order",
                                                      "documents": [{"_id": 9, "status": "DRAFT"}]}))
    assert code == 1 and "121" in why and "Rehearsal failed" in why, why
    with admin(entry) as client:
        assert client[DB]["t_order"].find_one({"_id": 9}) is None
    ok("a document the validator rejects fails its rehearsal: nothing to approve")


RELEASE = """[
  {"update": "t_order",
   "updates": [{"q": {"status": "DRAFT"}, "u": {"$set": {"status": "PAID"}}, "multi": true}]},
  {"insert": "t_order", "documents": [{"_id": 50, "status": "DRAFT", "total": 5, "ref": "A-50"}]}
]
"""
RAISE_50 = {"update": "t_order", "updates": [{"q": {"_id": 50}, "u": {"$inc": {"total": 1}}}]}


def _order(entry, oid):
    with admin(entry) as client:
        return client[DB]["t_order"].find_one({"_id": oid})


def _release(entry, p):
    """deploy: data, rehearsed as one transaction, landed as one, or not at all."""
    p.file("rel.json", RELEASE)
    p.file("raise.json", RAISE_50)
    code, doc, why = p.confirm("deploy", "rel.json", "raise.json")
    assert code == 0, (why, doc)
    assert [(m["line"], m["group"]) for m in doc["members"]] == [
        (2, "data_dml"), (4, "data_dml"), (1, "data_dml")], doc["members"]
    # the last update was rehearsed against the document the release inserts
    assert doc["members"][2]["row_set"]["count"] == 1, doc["members"][2]
    assert _order(entry, 50) is None and _order(entry, 1)["status"] == "DRAFT"
    ok("deploy rehearses a data release as one transaction: each command sees "
       "the ones before it")

    code, _, why = p.run("approve", "--card", doc["members"][0]["token"])
    assert code == 1 and "approved as a whole" in why, why
    p.approve(doc["batch"])
    with admin(entry) as client:          # a document moves after approval
        client[DB]["t_order"].update_one({"_id": 1}, {"$inc": {"total": 1}})
    code, _, why = p.confirm("deploy", "rel.json", "raise.json", "--confirm", doc["batch"])
    assert code == 1 and "statement 1" in why and "nothing was written" in why.lower(), why
    assert _order(entry, 50) is None and _order(entry, 1)["status"] == "DRAFT"
    ok("a release whose documents moved after approval rolls back whole")

    code, doc, why = p.confirm("deploy", "rel.json", "raise.json")
    p.approve(doc["batch"])
    code, res, why = p.confirm("deploy", "rel.json", "raise.json", "--confirm", doc["batch"])
    assert code == 0 and res["applied"], (why, res)
    assert _order(entry, 1)["status"] == "PAID" and _order(entry, 50)["total"] == 6
    ok("an approved release lands whole, in one commit")

    code, _, why = p.run("deploy", p.file("bad.json", [
        {"insert": "t_order", "documents": [{"_id": 51, "status": "DRAFT", "total": 1}]},
        {"insert": "t_order", "documents": [{"_id": 52, "status": "NOPE", "total": 1}]}]))
    assert code == 1 and "121" in why, why
    assert _order(entry, 51) is None
    ok("a release that fails at its second command keeps nothing of the first")

    code, _, why = p.run("deploy", p.file("mixed.json", [
        {"insert": "t_order", "documents": [{"_id": 53, "status": "DRAFT", "total": 1}]},
        {"createIndexes": "t_order", "indexes": [{"key": {"total": 1}, "name": "ix_t"}]}]))
    assert code == 1 and "cannot be rehearsed" in why, why
    assert _order(entry, 53) is None and "ix_t" not in indexes(entry, "t_order")
    ok("a release holding a command MongoDB runs outside a transaction is refused")


def _lint(entry, p):
    code, doc, why = p.confirm("apply", p.file("warn.json", (
        '{\n  "collMod": "t_order",\n'
        '  "validator": {"$jsonSchema": {"required": ["status", "total"]}},\n'
        '  "validationAction": "warn"\n}\n')))
    assert code == 0, why
    found = [(f["rule"], f["line"], f["severity"]) for f in doc["lint"]]
    assert ("mongo-validation-warn", 4, "warn") in found, found
    code, out, why = p.run("lint", "warn.json")
    assert code == 0 and "mongo-validation-warn" in out, (why, out)
    ok("lint: a validator that only warns is named in a real preview")


def _lease(entry, p):
    """autopilot: one approved lease lands covered writes, and nothing else."""
    code, doc, why = p.confirm("autopilot", "request", "--groups", "source",
                               "--max-writes", "2")
    assert code == 0 and len(doc["token"]) == 8, why
    view = {"collMod": "v_paid_big", "viewOn": "v_paid",
            "pipeline": [{"$match": {"total": {"$gt": 20}}}]}
    code, doc2, _ = p.confirm("apply", p.file("v1.json", view))
    assert code == 0 and doc2["will_apply"] is False         # a request is no lease
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "v1.json")
    assert code == 0 and res["applied"] and res["confirmed_via"] == "autopilot", (why, res)
    assert res["predicted"] and res["differs"] == [], res
    assert options(entry, "v_paid_big")["pipeline"] == view["pipeline"]
    code, doc3, why = p.confirm("apply", p.file("ix.json", {
        "createIndexes": "t_order", "indexes": [{"key": {"total": 1}, "name": "ix_lease"}]}))
    assert code == 0 and doc3["will_apply"] is False, why
    assert "does not cover structural" in doc3["autopilot"]["why"], doc3["autopilot"]
    assert "ix_lease" not in indexes(entry, "t_order")
    code, report, _ = p.confirm("autopilot", "report")
    assert [w["verdict"] for w in report["writes"]] == ["ok"], report
    assert p.run("autopilot", "off")[0] == 0
    ok("autopilot: an approved lease lands a covered, predicted write, and only that")


def _drop(entry, p):
    doc = p.preview("drop.json", {"drop": "t_order_line"})
    assert doc["destructive"] and ["v_order_lines", "VIEW",
                                   "reads what will not exist: t_order_line"] in \
        doc["rehearsal"]["broken"], doc
    assert options(entry, "t_order_line") is not None
    p.approve(doc["token"])
    code, res, why = p.confirm("apply", "drop.json", "--confirm", doc["token"])
    assert code == 3 and options(entry, "t_order_line") is None, (code, why, res)
    ok("a drop names the views it breaks, and lands as written-but-broken when approved")


def main():
    env = os.environ
    if not env.get("PYTHIA_MONGO_LIVE_HOST"):
        print("SKIP live check: PYTHIA_MONGO_LIVE_HOST is not set")
        return
    entry = admin_entry()
    check_connect(entry)
    if env.get("PYTHIA_MONGO_LIVE_DISPOSABLE") != "1":
        print("SKIP the read commands: PYTHIA_MONGO_LIVE_DISPOSABLE=1 is not set, "
              "and they create a user and drop a database")
        return
    agent = load_fixture(entry)
    p = check_reads(agent)
    ddl_round_trip(entry, p)
    check_writes(entry)
    print("OK")


if __name__ == "__main__":
    main()
