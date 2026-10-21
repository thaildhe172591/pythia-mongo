#!/usr/bin/env python3
"""pythia-mongo against a real MongoDB — a disposable one only.

1. Always (when PYTHIA_MONGO_LIVE_HOST is set): connect and `check`.
2. With PYTHIA_MONGO_LIVE_DISPOSABLE=1 only: the database pythia_live is
   dropped and rebuilt from tests/fixtures/app_owner.json, a user
   pythia_agent is made (the `read` role on it), and every read command
   runs through the command line as that user.

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


def check_connect(entry):
    p = Project(dict(entry, database="admin"))
    doc = p.json("check")
    server = {r["ITEM"]: r["VALUE"] for r in doc["rows"]}["server"]
    assert server.startswith("MongoDB ") and "database admin" in server, server
    ok(f"check: {server}")
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
    print("OK")


if __name__ == "__main__":
    main()
