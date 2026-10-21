"""The read tier for MongoDB: pythia's Learn movement, asked of the live
database.

MongoDB keeps much less than a SQL catalog. What it does keep — each
collection's validator, each view's pipeline, each index — is read through
listCollections and listIndexes, and printed as relaxed Extended JSON. A
collection has no column list: `cols` reads a sample of documents and says
how many it read. The only dependencies MongoDB records are views (viewOn,
$lookup, $graphLookup, $unionWith, $facet); the application code that
reads and writes a collection is invisible to it, and every impact report
says so.

`errors` counts the documents that break each collection's validator as it
stands, and runs each view over its first documents.
"""
from .catalog import ejson, like_regex, run

CATALOG_HOW = "catalog"
SAMPLE = 1000          # documents `cols` samples
VIEW_PROBE = 100       # documents `errors` runs each view over
TYPES = {"collection": "COLLECTION", "view": "VIEW", "timeseries": "TIMESERIES"}

BLIND_APP = (
    "application code — the services and jobs that read and write a "
    "collection through a driver — is not in the database: MongoDB records "
    "only the views that read it")
BLIND_ELSEWHERE = (
    "views in other databases, scheduled pipelines that $merge or $out into "
    "it, change streams and database triggers are not seen from this database")
BLIND_WRITERS = (
    "what writes into a collection is the application's, and is not recorded")


def kind(obj):
    return TYPES.get(obj.get("type"), str(obj.get("type", "")).upper())


def resolve(conn, name):
    found = run(conn, "collection.json", n=str(name))
    return found[0] if found else None


def everything(conn):
    return sorted(run(conn, "collections.json", p=like_regex("%")), key=lambda o: o["name"])


def object_names(conn, schema, pattern, fetch):
    rows = []
    for obj in sorted(run(conn, "collections.json", p=like_regex(pattern)),
                      key=lambda o: o["name"])[:int(fetch)]:
        opts = obj.get("options") or {}
        if obj.get("type") == "view":
            detail = f"on {opts.get('viewOn')}, {len(opts.get('pipeline') or [])} stages"
        elif opts.get("validator"):
            detail = (f"validator ({opts.get('validationLevel', 'strict')}, "
                      f"{opts.get('validationAction', 'error')})")
        else:
            detail = ""
        rows.append((obj["name"], kind(obj), detail))
    return ["NAME", "TYPE", "DETAIL"], rows


def _body(obj):
    """What a collection or view is defined by: a view's pipeline, a
    collection's validator. None for a collection without one."""
    opts = obj.get("options") or {}
    if obj.get("type") == "view":
        return {"viewOn": opts.get("viewOn"), "pipeline": opts.get("pipeline") or []}
    if not opts.get("validator"):
        return None
    return {k: opts[k] for k in ("validator", "validationLevel", "validationAction")
            if k in opts}


def _lines(obj):
    body = _body(obj)
    return ejson(body).split("\n") if body is not None else []


def source(conn, schema, name):
    obj = resolve(conn, name)
    if not obj:
        return []
    return [(obj["name"], i, text) for i, text in enumerate(_lines(obj), 1)]


# --- cols: fields read from a sample ----------------------------------------------------

def bson_type(value):
    name = type(value).__name__
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if name == "Int64":
        return "long"
    if isinstance(value, int):
        return "int" if -2 ** 31 <= value < 2 ** 31 else "long"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return {"ObjectId": "objectId", "datetime": "date", "Decimal128": "decimal",
            "Binary": "binData", "bytes": "binData", "Timestamp": "timestamp",
            "Regex": "regex", "Pattern": "regex", "UUID": "binData"}.get(name, name)


def _walk_fields(value, path, fields, seen):
    """Record each path (dotted; array elements as path[]) and its types,
    counting a path once per document."""
    entry = fields.setdefault(path, {"types": {}, "seen": 0})
    t = bson_type(value)
    entry["types"][t] = entry["types"].get(t, 0) + 1
    if path not in seen:
        seen.add(path)
        entry["seen"] += 1
    if isinstance(value, dict):
        for k, v in value.items():
            _walk_fields(v, f"{path}.{k}", fields, seen)
    elif isinstance(value, list):
        for v in value:
            _walk_fields(v, f"{path}[]", fields, seen)


def _declared(schema, prefix=""):
    """{path: (required, description)} from a $jsonSchema, nested objects too."""
    out = {}
    required = set(schema.get("required") or [])
    for key, spec in (schema.get("properties") or {}).items():
        path = f"{prefix}{key}"
        spec = spec if isinstance(spec, dict) else {}
        out[path] = (key in required, str(spec.get("description") or ""))
        if spec.get("properties"):
            out.update(_declared(spec, f"{path}."))
    return out


def columns(conn, schema, name):
    obj = resolve(conn, name)
    if not obj:
        return None
    docs = run(conn, "sample.json", n=obj["name"], k=SAMPLE)
    fields = {}
    for doc in docs:
        seen = set()
        for k, v in doc.items():
            _walk_fields(v, k, fields, seen)
    validator = (obj.get("options") or {}).get("validator") or {}
    declared = _declared(validator.get("$jsonSchema") or {})
    n = len(docs)
    rows = []
    for path, info in fields.items():
        req, desc = declared.get(path, (False, ""))
        types = sorted(info["types"], key=lambda t: (-info["types"][t], t))
        rows.append((path, ", ".join(types), f"{info['seen']} of {n}",
                     "yes" if req else "", desc))
    for path, (req, desc) in declared.items():
        if path not in fields:
            rows.append((path, "", f"0 of {n}", "yes" if req else "", desc))
    # a sample comes back in random order: sort, so the answer reads the same
    rows.sort(key=lambda r: (r[0] != "_id", r[0]))
    blind = None
    if n >= SAMPLE:
        total = run(conn, "count.json", n=obj["name"]).get("n")
        blind = (f"fields come from {n} sampled documents of about {total}: a field "
                 "few documents hold may be missing, and a field may hold more "
                 "types than these")
    return ["FIELD", "TYPES", "SEEN", "REQUIRED", "COMMENT"], rows, blind


# --- ddl: the commands that make it ------------------------------------------------------

def ddl(conn, schema, name):
    obj = resolve(conn, name)
    if not obj:
        return ""
    opts = dict(obj.get("options") or {})
    commands = [{"create": obj["name"], **opts}]
    if obj.get("type") != "view":
        indexes = [{k: v for k, v in ix.items() if k not in ("v", "ns")}
                   for ix in run(conn, "indexes.json", n=obj["name"])
                   if ix.get("name") != "_id_"]
        if indexes:
            commands.append({"createIndexes": obj["name"], "indexes": indexes})
    return ejson(commands)


def grep(conn, schema, text, fetch):
    needle, out = str(text).lower(), []
    for obj in everything(conn):
        for i, line in enumerate(_lines(obj), 1):
            if needle in line.lower():
                out.append((obj["name"], kind(obj), i, line))
                if len(out) >= int(fetch):
                    return ["NAME", "TYPE", "LINE", "TEXT"], out
    return ["NAME", "TYPE", "LINE", "TEXT"], out


# --- what a view reads, and what reads a collection -------------------------------------

def references(pipeline):
    """Every collection a pipeline reads, in stage order, nested pipelines
    ($lookup, $unionWith, $facet) included."""
    out = []
    for stage in pipeline or []:
        if not isinstance(stage, dict):
            continue
        for op, arg in stage.items():
            if op in ("$lookup", "$graphLookup") and isinstance(arg, dict):
                if isinstance(arg.get("from"), str):
                    out.append(arg["from"])
                out += references(arg.get("pipeline"))
            elif op == "$unionWith":
                if isinstance(arg, str):
                    out.append(arg)
                elif isinstance(arg, dict):
                    if isinstance(arg.get("coll"), str):
                        out.append(arg["coll"])
                    out += references(arg.get("pipeline"))
            elif op == "$facet" and isinstance(arg, dict):
                for sub in arg.values():
                    out += references(sub)
    return out


def reads_of(obj):
    """What a view reads: viewOn first, then its pipeline's collections."""
    if obj.get("type") != "view":
        return []
    opts = obj.get("options") or {}
    seen, out = set(), []
    for name in [opts.get("viewOn")] + references(opts.get("pipeline")):
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def walk(roots, depth, children):
    """Depth-first from each root, in the order a tree is read. An object
    reached twice is listed twice (that is the graph) but walked once."""
    rows, seen = [], set(roots)

    def visit(node, level):
        if level > depth:
            return
        for schema, name, otype, how in children(node):
            rows.append((level, schema, name, otype, how))
            if name not in seen:
                seen.add(name)
                visit(name, level + 1)

    for root in roots:
        visit(root, 1)
    return rows


def dependents(conn, schema, name, depth):
    objs = everything(conn)
    by_name = {o["name"]: o for o in objs}
    readers = {}
    for o in objs:
        for r in reads_of(o):
            readers.setdefault(r, []).append(o["name"])
    if name not in by_name and name not in readers:
        return None

    def children(node):
        return [(schema, v, kind(by_name[v]), CATALOG_HOW)
                for v in sorted(readers.get(node, []))]

    return walk([name], depth, children), [BLIND_APP, BLIND_ELSEWHERE]


def dependencies(conn, schema, name, depth):
    objs = everything(conn)
    by_name = {o["name"]: o for o in objs}
    if name not in by_name:
        return None

    def children(node):
        obj = by_name.get(node)
        return [(schema, r, kind(by_name[r]) if r in by_name else "MISSING", CATALOG_HOW)
                for r in (reads_of(obj) if obj else [])]

    return walk([name], depth, children), [BLIND_WRITERS]


# --- errors -------------------------------------------------------------------------------

def error_text(exc):
    """(code, first line of the message) of a driver error."""
    code = getattr(exc, "code", None)
    details = getattr(exc, "details", None) or {}
    message = str(details.get("errmsg") or exc).strip().splitlines()
    return code, (message[0] if message else str(exc))


def compile_errors(conn, schema, name, errors=Exception):
    objs = everything(conn)
    by_name = {o["name"]: o for o in objs}
    if name is not None:
        if name not in by_name:
            return None
        objs = [by_name[name]]
    rows, unchecked, views = [], [], 0
    for obj in (o for o in objs if o.get("type") != "view"):
        opts = obj.get("options") or {}
        validator = opts.get("validator")
        if not validator:
            unchecked.append(obj["name"])
            continue
        found = run(conn, "invalid.json", n=obj["name"], v=validator)
        n = found[0]["n"][0]["n"] if found and found[0].get("n") else 0
        if n:
            first = ", ".join(str(d.get("_id")) for d in found[0].get("first") or [])
            level = opts.get("validationLevel", "strict")
            action = opts.get("validationAction", "error")
            rows.append((obj["name"], kind(obj), None, None,
                         "error" if action == "error" else "warning",
                         f"{n} {'document fails' if n == 1 else 'documents fail'} the "
                         f"validator ({level}, {action}) — first _id: {first}"))
    for obj in (o for o in objs if o.get("type") == "view"):
        views += 1
        try:
            run(conn, "view-run.json", n=obj["name"], k=VIEW_PROBE)
        except errors as exc:
            code, message = error_text(exc)
            rows.append((obj["name"], "VIEW", None, None, "error",
                         f"{code}: {message}" if code is not None else message))
        missing = [r for r in reads_of(obj) if r not in by_name]
        if missing:
            rows.append((obj["name"], "VIEW", None, None, "error",
                         f"reads what does not exist: {', '.join(missing)}"))
    blind = []
    if unchecked:
        blind.append(f"{', '.join(unchecked)} {'has' if len(unchecked) == 1 else 'have'} "
                     "no validator: no document there was checked")
    if views:
        blind.append(f"each view ran over its first {VIEW_PROBE} documents only: an "
                     "expression that fails on a later document is not seen")
    return rows, "; ".join(blind) or None
