"""The write tier for MongoDB: one command document per file, read as
Extended JSON, and two ways through pythia-core's gate.

Data — insert, update, delete — is rehearsed: run inside a transaction and
aborted, as a SQL engine rehearses. Transactions need a replica set, so a
standalone server is refused (DESIGN.md §5).

Everything else runs outside any transaction in MongoDB — a view, a
validator, an index, a new or dropped collection — so it is PREDICTED
(pythia-core's predict tier): nothing runs before the approval. A new
validator is checked by counting the documents it would reject, a unique
index by looking for the keys it would meet twice, a view by running its
pipeline (once over no documents: does MongoDB accept it? then over its
first documents: does it run?), and the views built on it by running theirs
on top. After the approval core runs the command once (`execute`), and
`verify_written` reads back what landed and says how it differs from the
prediction.

JavaScript ($where, $function, $accumulator, code) and pipelines that write
($out, $merge) are refused wherever they appear: a prediction runs a
pipeline before anyone approves it, so it must never be able to write.
"""
import json

from .catalog import ejson, run, to_bson
from .read import error_text, everything, kind, reads_of, references, resolve

PROBE = 100             # documents a view's prediction runs it over
SAMPLE_ROWS = 10        # documents an UPDATE or DELETE preview shows

READS = ("aggregate", "find", "count", "distinct", "listCollections", "listIndexes",
         "collStats", "dbStats", "explain", "getMore")
USERS = ("createUser", "updateUser", "dropUser", "dropAllUsersFromDatabase",
         "grantRolesToUser", "revokeRolesFromUser", "createRole", "updateRole",
         "dropRole", "dropAllRolesFromDatabase", "grantRolesToRole",
         "revokeRolesFromRole", "grantPrivilegesToRole", "revokePrivilegesFromRole")
SESSION_KEYS = ("lsid", "txnNumber", "autocommit", "startTransaction", "$db",
                "writeConcern", "readConcern", "$readPreference")
JAVASCRIPT = ("$where", "$function", "$accumulator", "$code")
WRITING_STAGES = ("$out", "$merge")
VIEW_KEYS = ("viewOn", "pipeline")
VALIDATOR_KEYS = ("validator", "validationLevel", "validationAction")
EJSON_TYPES = ("$oid", "$numberLong", "$numberInt", "$numberDecimal", "$date",
               "$uuid", "$binary", "$eq")
BROAD_ROLES = ("root", "dbOwner", "userAdmin", "userAdminAnyDatabase",
               "dbAdminAnyDatabase", "readWriteAnyDatabase", "clusterAdmin",
               "__system", "restore")

CANNOT = ("Cannot classify this command, so it is refused rather than guessed at. "
          "apply takes one insert, update, delete, create, collMod, createIndexes, "
          "dropIndexes or drop command document per file.")
TXN = ("pythia-mongo owns the session and the transaction: leave lsid, "
       "txnNumber, writeConcern and readConcern out of the file.")


class _Duplicate(ValueError):
    pass


def _pairs(items):
    keys = [k for k, _ in items]
    for k in keys:
        if keys.count(k) > 1:
            raise _Duplicate(k)
    return dict(items)


def parse(text):
    """The command document, as plain JSON (Extended JSON forms kept)."""
    return json.loads(text, object_pairs_hook=_pairs)


def _keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)


def _by_id(q):
    """A filter that names one document by its _id."""
    if not isinstance(q, dict) or set(q) != {"_id"}:
        return False
    v = q["_id"]
    return not isinstance(v, (dict, list)) or (
        isinstance(v, dict) and len(v) == 1 and set(v) <= set(EJSON_TYPES))


def classify(text):
    """(group, None) or (None, why it is refused)."""
    stripped = str(text or "").strip()
    if not stripped:
        return None, "The file holds no command."
    if stripped.startswith(("db.", "use ", "show ", "rs.", "sh.")):
        return None, ("This is mongosh JavaScript, and it is refused: write the "
                      "command document itself — {\"insert\": \"t_order\", "
                      "\"documents\": [...]} — one per file, in Extended JSON.")
    try:
        cmd = parse(stripped)
    except _Duplicate as e:
        return None, (f'"{e}" appears twice in one document: which one MongoDB '
                      "would use is not something to guess at.")
    except ValueError as e:
        return None, (f"Cannot read the file as one Extended JSON command document: "
                      f"{e}. Write the command document, not mongosh JavaScript.")
    if isinstance(cmd, list):
        return None, ("A file holds one command document: several commands go "
                      "in several files.")
    if not isinstance(cmd, dict):
        return None, "A file holds one command document: a JSON object."
    if not cmd:
        return None, "The file holds no command."
    keys = set(_keys(cmd))
    if keys & set(JAVASCRIPT):
        return None, ("JavaScript runs inside the server and can do anything "
                      f"({', '.join(sorted(keys & set(JAVASCRIPT)))}): refused.")
    for stage in WRITING_STAGES:
        if stage in keys:
            return None, (f"{stage} writes another collection from inside a "
                          "pipeline: refused — a view cannot hold it, and a "
                          "prediction runs a pipeline before anyone approves it.")
    name = next(iter(cmd))
    if name in READS:
        return None, ("apply takes writes; reads go through ls, src, cols and "
                      "grep — and an aggregate can write with $out or $merge.")
    if name in USERS:
        return None, ("Users and roles are a DBA's to manage, by hand: a "
                      "createUser command carries a password into the file and "
                      "into pythia's journal.")
    if name == "renameCollection":
        return None, ("renameCollection can move a collection to another database, "
                      "and every view and application that names it breaks: "
                      "refused. Create the new collection and copy its documents "
                      "in reviewed steps, or a DBA renames it.")
    if name == "dropDatabase":
        return None, ("dropDatabase removes every collection at once: refused. A "
                      "DBA runs it, by hand.")
    if name.lower() == "findandmodify":
        return None, ("findAndModify changes one document and returns it: write it "
                      "as an update or a delete, so its documents are shown "
                      "before it runs.")
    if name == "mapReduce":
        return None, "mapReduce runs JavaScript inside the server: refused."
    if set(cmd) & set(SESSION_KEYS):
        return None, TXN
    if cmd.get("bypassDocumentValidation"):
        return None, ("bypassDocumentValidation skips the collection's validator: "
                      "refused.")
    target = cmd[name]
    if name not in ("insert", "update", "delete", "create", "collMod",
                    "createIndexes", "dropIndexes", "drop"):
        return None, CANNOT
    if not isinstance(target, str) or not target or "$" in target or "\0" in target:
        return None, "The command must name its collection as a string."
    if target.startswith("system."):
        return None, "system collections are MongoDB's own: refused."
    return _group(name, cmd)


def _group(name, cmd):
    if name == "insert":
        docs = cmd.get("documents")
        if not isinstance(docs, list) or not docs:
            return None, "The insert holds no document."
        return "data_dml", None
    if name in ("update", "delete"):
        many = cmd.get("updates" if name == "update" else "deletes")
        if not isinstance(many, list) or len(many) != 1:
            return None, (f"A {name} holds one statement here: several are several "
                          "statements, one per file, each previewed on its own.")
        one = many[0]
        if not isinstance(one, dict) or not isinstance(one.get("q"), dict):
            return None, f"The {name} statement needs its filter, \"q\"."
        if name == "update":
            if one.get("upsert"):
                return None, ("An upsert inserts a document when none matches, so "
                              "its documents cannot be shown beforehand: write an "
                              "insert, or an update.")
            if not one.get("multi") and not _by_id(one["q"]):
                return None, ('Without "multi": true an update changes one of the '
                              "documents its filter matches — which one is not "
                              "something the developer can see beforehand. Set "
                              '"multi": true, or name the document by its _id.')
        else:
            if one.get("limit") not in (0, 1):
                return None, ('A delete names its "limit": 0 for every document its '
                              "filter matches, 1 for one named by its _id.")
            if one["limit"] == 1 and not _by_id(one["q"]):
                return None, ('"limit": 1 deletes one of the documents its filter '
                              "matches — which one is not something the developer "
                              "can see beforehand. Use \"limit\": 0, or name the "
                              "document by its _id.")
        return "data_dml", None
    if name == "create":
        return ("source" if "viewOn" in cmd else "structural"), None
    if name == "collMod":
        changes = set(cmd) - {"collMod", "comment"}
        if not changes:
            return None, "collMod that changes nothing: nothing to apply."
        for family in (VIEW_KEYS, VALIDATOR_KEYS):
            if changes & set(family):
                if changes - set(family):
                    return None, ("collMod makes one change per file — a view, a "
                                  "validator, or an option — so each is previewed "
                                  "and restored on its own.")
                if family == VIEW_KEYS and changes != set(VIEW_KEYS):
                    return None, "collMod of a view names both viewOn and pipeline."
                return "source", None
        return "structural", None
    if name == "createIndexes":
        specs = cmd.get("indexes")
        if not isinstance(specs, list) or not specs or not all(
                isinstance(s, dict) and isinstance(s.get("key"), dict)
                and isinstance(s.get("name"), str) for s in specs):
            return None, "Every index names its \"key\" and its \"name\"."
        return "structural", None
    if name == "dropIndexes" and "index" not in cmd:
        return None, "dropIndexes names the index it drops."
    return "structural", None


def prepare_statement(text, group):
    return json.dumps(parse(text), indent=2, ensure_ascii=False)


def _cmd(stmt):
    cmd = parse(stmt)
    return next(iter(cmd)), cmd


def parse_object(stmt, group):
    if group != "source":
        return None
    name, cmd = _cmd(stmt)
    otype = "VIEW" if (name == "create" or set(cmd) & set(VIEW_KEYS)) else "VALIDATOR"
    return {"type": otype, "name": cmd[name], "schema": None}


def destructive_reason(stmt, group):
    name, cmd = _cmd(stmt)
    if name == "drop":
        return ("drop removes the collection — every document in it — or the "
                "view, and every view built on it reads nothing")
    if name == "dropIndexes":
        if cmd.get("index") == "*":
            return ("dropIndexes \"*\" drops every index but _id: each query that "
                    "used one scans the collection")
        return ("dropping an index makes every query that used it scan the "
                "collection; bringing it back is a full build")
    if name in ("update", "delete"):
        one = cmd["updates" if name == "update" else "deletes"][0]
        if one.get("q") == {}:
            return f"an empty filter: the {name} reaches every document in {cmd[name]}"
    return None


def dml_probe(stmt):
    name, cmd = _cmd(stmt)
    if name not in ("update", "delete"):
        return None
    one = cmd["updates" if name == "update" else "deletes"][0]
    return cmd[name], one["q"]


def measure_row_set(conn, target, pred):
    found = run(conn, "probe.json", n=target, f=to_bson(pred))
    count, fingerprint = (int(found[0]["n"]), str(found[0]["h"])) if found else (0, "0")
    docs = run(conn, "probe-sample.json", n=target, f=to_bson(pred), k=SAMPLE_ROWS + 1)
    return {"target": target, "predicate": ejson(pred, indent=None), "count": count,
            "hash": fingerprint, "columns": ["DOCUMENT"],
            "sample": [[ejson(d, indent=None)] for d in docs[:SAMPLE_ROWS]],
            "truncated": len(docs) > SAMPLE_ROWS}


# --- snapshot and restore ---------------------------------------------------------------

def _definition(obj, otype):
    opts = (obj or {}).get("options") or {}
    if otype == "VIEW":
        return {"viewOn": opts.get("viewOn"), "pipeline": opts.get("pipeline") or []}
    return {"validator": opts.get("validator") or {},
            "validationLevel": opts.get("validationLevel", "strict"),
            "validationAction": opts.get("validationAction", "error")}


def snapshot(conn, schema, group, ident):
    """What the statement replaces: a view's pipeline, a collection's
    validator — as it stands, in Extended JSON."""
    if group != "source":
        return {}
    obj = resolve(conn, ident["name"])
    want = "view" if ident["type"] == "VIEW" else "collection"
    if not obj or obj.get("type") != want:
        return {}
    return {ident["name"]: ejson(_definition(obj, ident["type"]))}


def restore_statement(group, ident, before, outcome):
    if group != "source":
        return ""
    if not before:
        return json.dumps({"drop": ident["name"]}, indent=2)
    return json.dumps({"collMod": ident["name"], **json.loads(before)}, indent=2,
                      ensure_ascii=False)


# --- the rehearsal: data in a transaction, everything else predicted -----------------

def _said(exc):
    code, message = error_text(exc)
    return f"{code}: {message}" if code is not None else message


def _reply_error(reply):
    """A command's own failure in its reply: MongoDB reports a document that
    breaks a validator there, not as an exception."""
    errs = reply.get("writeErrors") or []
    if errs:
        return f"{errs[0].get('code')}: {errs[0].get('errmsg')}"
    wce = reply.get("writeConcernError")
    if wce:
        return f"{wce.get('code')}: {wce.get('errmsg')}"
    return None


def _replica_set(conn):
    hello = run(conn, "server-hello.json")
    return bool(hello.get("setName") or hello.get("msg") == "isdbgrid")


def rehearse(conn, schema, group, stmt, ident, snap, errors=Exception):
    name, cmd = _cmd(stmt)
    if group == "data_dml":
        return _rehearse_data(conn, cmd, errors)
    try:
        if group == "source" and ident["type"] == "VALIDATOR":
            out = _predict_validator(conn, cmd, ident, errors)
        elif group == "source":
            out = _predict_view(conn, name, cmd, ident, errors)
        else:
            out = _predict_structural(conn, name, cmd, errors)
    except errors as exc:
        out = {"error": f"the prediction could not finish: {_said(exc)}"}
    out["predicted"] = True
    return out


def _rehearse_data(conn, cmd, errors):
    if not _replica_set(conn):
        return {"error": "Data writes are rehearsed in a transaction, and transactions "
                         "need a replica set: this server is standalone. A single-node "
                         "replica set is enough for development."}
    try:
        reply = conn.run_statement(to_bson(cmd), True)
    except errors as exc:
        return {"error": _said(exc)}
    failed = _reply_error(reply)
    if failed:
        return {"error": failed}
    return {"error": None, "object": None, "type": None, "after": None,
            "rows": int(reply.get("n", 0)), "broken": [], "own_errors": [],
            "verified": True, "blind": None,
            "notes": ["the rehearsal ran in a transaction and was aborted: change "
                      "streams and database triggers never saw it"]}


def _base(name, otype, after, **more):
    return {"error": None, "object": name, "type": otype, "after": after, "rows": None,
            "broken": [], "own_errors": [], "verified": True, "blind": None,
            "notes": [], **more}


def _failing(conn, coll, validator):
    """(how many documents break a validator, the first of them)."""
    found = run(conn, "invalid.json", n=coll, v=validator)
    if not found or not found[0].get("n"):
        return 0, ""
    first = ", ".join(str(d.get("_id")) for d in found[0].get("first") or [])
    return found[0]["n"][0]["n"], first


def _failing_line(n, first, level, action, new=True):
    noun = "document fails" if n == 1 else "documents fail"
    which = "the new validator" if new else "the validator"
    return f"{n} {noun} {which} ({level}, {action}) — first _id: {first}"


def _predict_validator(conn, cmd, ident, errors):
    coll = ident["name"]
    obj = resolve(conn, coll)
    if not obj:
        return {"error": f"no collection named {coll}"}
    if obj.get("type") == "view":
        return {"error": f"{coll} is a view: a view has no validator"}
    now = _definition(obj, "VALIDATOR")
    new = {k: to_bson(cmd[k]) if k == "validator" else cmd[k] for k in VALIDATOR_KEYS
           if k in cmd}
    definition = {**now, **new}
    out = _base(coll, "VALIDATOR", ejson(definition))
    if not definition["validator"]:
        out["notes"].append("the validator is removed: no document is checked any more")
        out["prediction"] = {"failing": 0}
        return out
    try:
        n, first = _failing(conn, coll, definition["validator"])
    except errors as exc:
        return {"error": f"MongoDB would refuse this validator: {_said(exc)}"}
    if n:
        out["broken"] = [(coll, "COLLECTION", _failing_line(
            n, first, definition["validationLevel"], definition["validationAction"]))]
    out["prediction"] = {"failing": n}
    return out


def _run_pipeline(conn, source, pipeline):
    return run(conn, "pipeline-run.json", n=source, p=pipeline)


def _predict_view(conn, name, cmd, ident, errors):
    view = ident["name"]
    obj = resolve(conn, view)
    if name == "create" and obj:
        what = "view" if obj.get("type") == "view" else "collection"
        return {"error": f"a {what} named {view} exists" + (
            ": change it with collMod" if what == "view" else "")}
    if name == "collMod" and (not obj or obj.get("type") != "view"):
        return {"error": f"no view named {view}: create it first"}
    source, pipeline = cmd["viewOn"], to_bson(cmd.get("pipeline") or [])
    try:
        _run_pipeline(conn, source, [{"$match": {"_id": {"$exists": False}}}]
                      + pipeline + [{"$count": "n"}])
    except errors as exc:
        return {"error": f"MongoDB would refuse this pipeline: {_said(exc)}"}
    out = _base(view, "VIEW", ejson({"viewOn": source, "pipeline": pipeline}))
    objs = everything(conn)
    by_name = {o["name"]: o for o in objs}
    failed = _view_failure(conn, source, pipeline, errors)
    if failed:
        out["own_errors"].append((view, "VIEW", failed))
    missing = [r for r in [source] + references(pipeline)
               if r not in by_name and r != view]
    if missing:
        out["own_errors"].append((view, "VIEW", f"reads what does not exist: "
                                                f"{', '.join(missing)}"))
    out["broken"], through = _views_on_top(conn, view, source, pipeline, objs, errors)
    blind = [f"the new pipeline ran until its first {PROBE} documents came out: an "
             "expression that fails on a later document is not seen"]
    if through:
        blind.append("views that read it through $lookup or $unionWith were not run "
                     f"against the new definition: {', '.join(through)}")
    out.update(verified=False, blind="; ".join(blind),
               prediction={"own": out["own_errors"], "broken": out["broken"]})
    return out


def _view_failure(conn, source, pipeline, errors):
    try:
        _run_pipeline(conn, source, pipeline + [{"$limit": PROBE}, {"$count": "n"}])
    except errors as exc:
        return f"fails over its first {PROBE} documents: {_said(exc)}"
    return None


def _views_on_top(conn, view, source, pipeline, objs, errors):
    """Views built on this one through viewOn, each run on top of the new
    definition, as far up as they go; and those that read it otherwise."""
    broken, through = [], []

    def climb(name, base_source, base_pipeline, seen):
        for o in objs:
            opts = o.get("options") or {}
            if o.get("type") != "view" or o["name"] in seen:
                continue
            if opts.get("viewOn") == name:
                composed = base_pipeline + list(opts.get("pipeline") or [])
                failed = _view_failure(conn, base_source, composed, errors)
                if failed:
                    broken.append((o["name"], "VIEW", failed))
                climb(o["name"], base_source, composed, seen | {o["name"]})
            elif name in reads_of(o):
                through.append(o["name"])

    climb(view, source, list(pipeline), {view})
    return broken, sorted(set(through))


def _index_holds(spec):
    """The documents an index holds, as a filter: its partial filter, or for
    a sparse index those with at least one of its fields."""
    if spec.get("partialFilterExpression"):
        return to_bson(spec["partialFilterExpression"])
    if spec.get("sparse"):
        return {"$or": [{k: {"$exists": True}} for k in spec["key"]]}
    return {}


def _predict_structural(conn, name, cmd, errors):
    coll = cmd[name]
    obj = resolve(conn, coll)
    otype = kind(obj) if obj else "COLLECTION"
    out = _base(coll, otype, None)
    if name == "create":
        if obj:
            return {"error": f"a {kind(obj).lower()} named {coll} exists"}
        out["notes"].append("a new, empty collection" + (
            " with a validator" if cmd.get("validator") else ""))
        return out
    if name in ("drop", "collMod") and not obj:
        return {"error": f"no collection or view named {coll}"}
    if name == "drop":
        out["broken"] = [(o["name"], kind(o), f"reads what will not exist: {coll}")
                         for o in everything(conn) if coll in reads_of(o)]
        return out
    if name == "collMod":
        out.update(verified=False, blind="pythia-mongo does not model this option: "
                   "MongoDB checks it when the command runs")
        return out
    if obj and obj.get("type") == "view":
        return {"error": f"{coll} is a view: a view has no indexes"}
    existing = {ix["name"]: ix for ix in run(conn, "indexes.json", n=coll)} if obj else {}
    if name == "dropIndexes":
        index = cmd["index"]
        names = index if isinstance(index, list) else [index]
        for ix in names:
            if ix == "*":
                continue
            if isinstance(ix, dict):
                if not any(e.get("key") == ix for e in existing.values()):
                    return {"error": f"no index on {coll} has the key {ejson(ix, None)}"}
            elif ix not in existing:
                return {"error": f"no index named {ix} on {coll}"}
        out["type"] = "INDEX"
        return out
    out["type"] = "INDEX"
    for spec in cmd["indexes"]:
        have = existing.get(spec["name"])
        if have and have.get("key") != spec["key"]:
            return {"error": f"an index named {spec['name']} exists on {coll} with the "
                             f"key {ejson(have.get('key'), None)}: MongoDB would refuse it"}
        if have:
            out["notes"].append(f"{spec['name']} exists with this key: MongoDB leaves "
                                "it as it is")
            continue
        if spec.get("unique") and obj:
            group = {k.replace(".", "_"): f"${k}" for k in spec["key"]}
            dups = run(conn, "duplicates.json", n=coll, f=_index_holds(spec), g=group)
            if dups:
                keys = "; ".join(f"{ejson(d['_id'], None)} ×{d['n']}" for d in dups)
                return {"error": f"a unique index {spec['name']} would meet duplicate "
                                 f"keys — {keys}: MongoDB would refuse the build"}
            out.update(verified=False, blind="an array-valued key is compared as a "
                       "whole array here, not element by element as the index will")
    out["notes"].append("the build reads every document; the collection stays "
                        "readable and writable while it builds")
    return out


# --- after the approval: run once, then read back what landed ----------------------------

def execute(conn, schema, group, stmt, ident, errors=Exception):
    """Run a predicted command once, outside any transaction. Each of these
    commands is applied whole or not at all, so a refusal from the server
    wrote nothing; anything else leaves it unknown."""
    _, cmd = _cmd(stmt)
    try:
        reply = conn.run_statement(to_bson(cmd), False)
    except errors as exc:
        names = {c.__name__ for c in type(exc).__mro__}
        if "OperationFailure" in names and "WriteConcernError" not in names:
            return {"error": _said(exc)}
        return {"escaped": "the command was sent, and no answer says whether it "
                           "landed", "error": _said(exc)}
    wce = reply.get("writeConcernError")
    if wce:
        return {"escaped": "the server applied it but could not confirm its write "
                           "concern", "error": f"{wce.get('code')}: {wce.get('errmsg')}"}
    if reply.get("writeErrors"):
        return {"error": _reply_error(reply)}
    return {}


def verify_written(conn, schema, group, stmt, ident, outcome, errors=Exception):
    name, cmd = _cmd(stmt)
    prediction = outcome.get("prediction") or {}
    if group == "source" and ident["type"] == "VALIDATOR":
        return _verify_validator(conn, cmd, ident, prediction)
    if group == "source":
        return _verify_view(conn, cmd, ident, prediction, outcome, errors)
    return _verify_structural(conn, name, cmd, outcome)


def _verify_validator(conn, cmd, ident, prediction):
    coll = ident["name"]
    obj = resolve(conn, coll)
    now = _definition(obj, "VALIDATOR") if obj else {}
    differs = [f"{coll} reads back {k} = {ejson(now.get(k), None)}, not what was written"
               for k in VALIDATOR_KEYS if k in cmd and now.get(k) != to_bson(cmd[k])]
    broken = []
    if obj and now.get("validator"):
        n, first = _failing(conn, coll, now["validator"])
        if n:
            broken.append((coll, "COLLECTION", _failing_line(
                n, first, now["validationLevel"], now["validationAction"], new=False)))
        said = prediction.get("failing")
        if said is not None and n != said:
            differs.append(f"{n} documents fail the validator now; the prediction "
                           f"said {said}")
    return {"broken": broken, "own_errors": [], "differs": differs}


def _verify_view(conn, cmd, ident, prediction, outcome, errors):
    view = ident["name"]
    obj = resolve(conn, view)
    differs = []
    if not obj or obj.get("type") != "view":
        return {"broken": [], "own_errors": [],
                "differs": [f"no view named {view} after the write"]}
    want = {"viewOn": cmd["viewOn"], "pipeline": to_bson(cmd.get("pipeline") or [])}
    if _definition(obj, "VIEW") != want:
        differs.append(f"{view} reads back as {ejson(_definition(obj, 'VIEW'), None)}, "
                       "not what was written")
    own = []
    failed = _view_failure(conn, want["viewOn"], want["pipeline"], errors)
    if failed:
        own.append((view, "VIEW", failed))
    objs = everything(conn)
    broken, _ = _views_on_top(conn, view, want["viewOn"], want["pipeline"], objs, errors)
    seen = {tuple(f) for f in (prediction.get("own") or []) + (prediction.get("broken") or [])}
    differs += [f"{f[0]} {f[2]} — the prediction did not see it"
                for f in own + broken if tuple(f) not in seen]
    by_name = {o["name"] for o in objs}
    own += [f for f in outcome.get("own_errors") or []
            if "reads what does not exist" in f[2] and
            any(r not in by_name for r in [want["viewOn"]] + references(want["pipeline"]))]
    return {"broken": broken, "own_errors": own, "differs": differs}


def _verify_structural(conn, name, cmd, outcome):
    coll = cmd[name]
    obj = resolve(conn, coll)
    differs = []
    if name == "create" and not obj:
        differs.append(f"no collection named {coll} after the write")
    if name == "drop" and obj:
        differs.append(f"{coll} still exists after the write")
    if name in ("createIndexes", "dropIndexes"):
        have = {ix["name"]: ix for ix in run(conn, "indexes.json", n=coll)} if obj else {}
        if name == "createIndexes":
            for spec in cmd["indexes"]:
                got = have.get(spec["name"])
                if not got or got.get("key") != to_bson(spec["key"]):
                    differs.append(f"no index named {spec['name']} with this key on "
                                   f"{coll} after the write")
        else:
            index = cmd["index"]
            for ix in (index if isinstance(index, list) else [index]):
                if isinstance(ix, str) and ix != "*" and ix in have:
                    differs.append(f"{ix} is still on {coll} after the write")
    return {"broken": list(outcome.get("broken") or []), "own_errors": [],
            "differs": differs}


def privilege_warning(conn, schema):
    info = (run(conn, "connection-status.json") or {}).get("authInfo") or {}
    roles = sorted({r.get("role") for r in info.get("authenticatedUserRoles") or []}
                   & set(BROAD_ROLES))
    if not roles:
        return None
    users = info.get("authenticatedUsers") or [{}]
    who = users[0].get("user") or "this user"
    return (f"! {who} holds {', '.join(roles)}: it can do far more than this change "
            "needs. A user with readWrite on this database (and dbAdmin for indexes, "
            "validators and views) is safer.")


# --- the release tier ---------------------------------------------------------------------

def split_script(text):
    """(line, statement) for each command document of a release file: one
    document, or a JSON array of them. Anything else comes back whole, at
    line 1, for classify to say why it is refused."""
    stripped = str(text or "").strip()
    if not stripped:
        return []
    start = text.index(stripped[0])
    if stripped[0] != "[":
        return [(1, stripped)]
    decoder, out = json.JSONDecoder(), []
    i, n = start + 1, len(text)

    def skip(j):
        while j < n and text[j] in " \t\r\n":
            j += 1
        return j
    try:
        i = skip(i)
        if i < n and text[i] == "]":
            return [] if not text[i + 1:].strip() else [(1, stripped)]
        while True:
            _, end = decoder.raw_decode(text, i)
            out.append((text.count("\n", 0, i) + 1, text[i:end]))
            i = skip(end)
            if i < n and text[i] == ",":
                i = skip(i + 1)
                continue
            if i < n and text[i] == "]" and not text[i + 1:].strip():
                return out
            return [(1, stripped)]
    except ValueError:
        return [(1, stripped)]

