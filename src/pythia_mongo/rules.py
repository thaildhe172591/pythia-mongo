"""MongoDB's lint rules: what MongoDB accepts and a reviewer would not.

There is no SQL to read here: the rules read command documents — how a
validator lets documents through, what an index does to them, what an
update leaves of them. What MongoDB refuses itself is left to the rehearsal
or the prediction.
"""
import json

from .write import parse


def _doc(stmt):
    try:
        cmd = parse(stmt)
    except ValueError:
        return None, None
    if not isinstance(cmd, dict) or not cmd:
        return None, None
    return next(iter(cmd)), cmd


def _line_of(stmt, key):
    """The line a key first stands on in the statement's text."""
    at = stmt.find(json.dumps(key))
    return stmt.count("\n", 0, at) + 1 if at >= 0 else 1


def validation_warn(stmt, group, run):
    _, cmd = _doc(stmt)
    if (cmd or {}).get("validationAction") == "warn":
        return [(_line_of(stmt, "validationAction"), "validationAction \"warn\" writes "
                 "every document that breaks the validator anyway, and only logs it — "
                 "\"error\" refuses it")]
    return []


def validation_off(stmt, group, run):
    _, cmd = _doc(stmt)
    if (cmd or {}).get("validationLevel") == "off":
        return [(_line_of(stmt, "validationLevel"), "validationLevel \"off\" stops "
                 "checking documents at all: the validator stays, and enforces nothing")]
    return []


def validator_required(stmt, group, run):
    name, cmd = _doc(stmt)
    schema = (cmd or {}).get("validator", {})
    schema = schema.get("$jsonSchema") if isinstance(schema, dict) else None
    if name in ("create", "collMod") and isinstance(schema, dict) \
            and not schema.get("required"):
        return [(_line_of(stmt, "$jsonSchema"), "a $jsonSchema with no \"required\" "
                 "list accepts a document that holds none of its fields")]
    return []


def collection_validator(stmt, group, run):
    name, cmd = _doc(stmt)
    if name != "create" or "viewOn" in cmd or cmd.get("validator"):
        return []
    for other in run:
        o_name, o_cmd = _doc(other)
        if o_name == "collMod" and o_cmd.get("collMod") == cmd["create"] \
                and o_cmd.get("validator"):
            return []
    return [(1, f"collection {cmd['create']} has no validator in this change: it "
             "accepts any document — say what one holds, in the same change")]


def unique_optional(stmt, group, run):
    name, cmd = _doc(stmt)
    if name != "createIndexes":
        return []
    out = []
    for spec in cmd.get("indexes") or []:
        keys = list((spec or {}).get("key") or {})
        if spec.get("unique") and not spec.get("sparse") \
                and not spec.get("partialFilterExpression"):
            out.append((_line_of(stmt, spec.get("name", "unique")), f"unique index "
                        f"{spec.get('name')}: every document without "
                        f"{', '.join(keys)} counts as null, and a second one is refused "
                        "— add a partialFilterExpression with $exists if the field is "
                        "optional"))
    return out


def ttl(stmt, group, run):
    name, cmd = _doc(stmt)
    if name != "createIndexes":
        return []
    return [(_line_of(stmt, "expireAfterSeconds"), f"index {spec.get('name')} has "
             f"expireAfterSeconds: the server deletes every document older than "
             f"{spec['expireAfterSeconds']} seconds, unasked and unjournaled")
            for spec in cmd.get("indexes") or [] if "expireAfterSeconds" in (spec or {})]


def update_replacement(stmt, group, run):
    name, cmd = _doc(stmt)
    if name != "update":
        return []
    out = []
    for one in cmd.get("updates") or []:
        u = (one or {}).get("u")
        if isinstance(u, dict) and u and not any(str(k).startswith("$") for k in u):
            out.append((_line_of(stmt, "u"), "\"u\" is a replacement document: every "
                        "field it does not name is removed from each document it "
                        "matches — use $set to change fields"))
    return out


RULES = [
    {"id": "mongo-validation-warn", "severity": "warn",
     "summary": "a validator refuses what breaks it (validationAction error)",
     "check": validation_warn},
    {"id": "mongo-validation-off", "severity": "warn",
     "summary": "a validator is enforced (validationLevel not off)",
     "check": validation_off},
    {"id": "mongo-validator-required", "severity": "info",
     "summary": "a $jsonSchema says which fields are required",
     "check": validator_required},
    {"id": "mongo-collection-validator", "severity": "warn",
     "summary": "every new collection carries a validator in the same change",
     "check": collection_validator},
    {"id": "mongo-unique-optional", "severity": "warn",
     "summary": "a unique index on an optional field is partial",
     "check": unique_optional},
    {"id": "mongo-ttl", "severity": "warn",
     "summary": "a TTL index deletes documents: said out loud", "check": ttl},
    {"id": "mongo-update-replacement", "severity": "warn",
     "summary": "an update changes fields ($set), not whole documents",
     "check": update_replacement},
]
