"""MongoDB, through pymongo, as a pythia-core engine.

It answers the connect tier (here), the read tier (read.py), and the write
and predict tiers (write.py). MongoDB has no SQL and no catalog of
dependencies: what it keeps is read as command documents (catalog.py), and
what it cannot see — the application code around it — is said in every
answer that depends on it. Data is rehearsed in a transaction; everything
else is predicted, written once, and read back (pythia-core's predict tier).
"""
import copy
import sys

from . import __version__, guard, read, write
from .catalog import run

# reads a transaction may hold; listCollections and listIndexes it may not
IN_TRANSACTION = ("aggregate", "find")

FLOOR = (7, 0)          # MongoDB 7.0: the oldest CI tests, and the oldest still supported

CONFIG_REL = ".pythia/mongo/connections.json"
REQUIRED = ("host", "database")


class MongoConn:
    """One client and the database a connection names, and the transaction a
    rehearsal opens. pythia-core commits it after an approval and aborts it
    after a preview, as it does a SQL engine's."""

    def __init__(self, client, db):
        self.client, self.db, self.session = client, db, None

    def _within(self, command):
        first = next(iter(command))
        return self.session if self.session is not None and first in IN_TRANSACTION \
            else None

    def run(self, name, command, cursor, admin):
        db = self.client.admin if admin else self.db
        if cursor:
            return list(db.cursor_command(command, session=self._within(command)))
        return db.command(command, session=self._within(command))

    def run_statement(self, command, in_txn):
        """A statement of the developer's: inside the rehearsal's transaction,
        or on its own (a predicted command, after the approval)."""
        if in_txn and self.session is None:
            self.session = self.client.start_session()
            self.session.start_transaction()
        return self.db.command(command, session=self.session if in_txn else None)

    def commit(self):
        session, self.session = self.session, None
        if session is not None:
            try:
                session.commit_transaction()
            finally:
                session.end_session()

    def rollback(self):
        session, self.session = self.session, None
        if session is not None:
            try:
                if session.in_transaction:
                    session.abort_transaction()
            finally:
                session.end_session()


class MongoEngine:
    name = "mongo"
    label = "MongoDB"
    command = "pythia-mongo"
    env_prefix = "PYTHIA_MONGO"
    version = __version__
    bind_style = "document"
    default_port = 27017
    rollback_notes = {
        "source": "Yes — a view's pipeline and a collection's validator are "
                  "snapshotted before every write; a new view's undo is a drop.",
        "comments": "Not used: MongoDB keeps no comments on objects (a field's "
                    "description lives in the $jsonSchema validator).",
        "data_dml": "No. After commit only a backup, or a point-in-time restore, "
                    "brings documents back. Revalidation checks the documents; it is "
                    "not an undo.",
        "structural": "No. A dropped collection or index is gone; the prediction "
                      "shows what would read what is dropped.",
        "grants": "Not used: users and roles are a DBA's, by hand.",
        "session": "Not used: MongoDB has no session settings to apply.",
    }

    # --- the connection's life ------------------------------------------------

    def driver_errors(self):
        try:
            import pymongo.errors
        except ImportError:
            sys.exit("The 'pymongo' package is required to connect: "
                     "pip install pymongo")
        return (pymongo.errors.PyMongoError,)

    def connect(self, entry):
        if entry.get("uri"):
            sys.exit('"uri" is not read: a connection string carries the password '
                     "into every place it is printed. Give \"host\", \"port\", "
                     f"\"database\", \"user\" and \"password\" in {CONFIG_REL}.")
        gaps = [k for k in REQUIRED if not entry.get(k)]
        if gaps:
            sys.exit(f"Connection is missing {', '.join(map(repr, gaps))} — "
                     f"fill in {CONFIG_REL}.")
        for flag in ("tls", "direct"):
            if flag in entry and not isinstance(entry[flag], bool):
                sys.exit(f'"{flag}" must be true or false — got {entry[flag]!r} '
                         f"in {CONFIG_REL}.")
        import pymongo
        kw = {"port": int(entry.get("port") or self.default_port)}
        if entry.get("user"):
            kw.update(username=entry["user"], password=entry.get("password") or "",
                      authSource=entry.get("auth_source") or "admin")
        kw["tls"] = bool(entry.get("tls", False))
        if entry.get("replica_set"):
            kw["replicaSet"] = entry["replica_set"]
        if "direct" in entry:
            kw["directConnection"] = entry["direct"]
        kw.update(appname=self.command, serverSelectionTimeoutMS=10000,
                  connectTimeoutMS=10000)
        client = pymongo.MongoClient(entry["host"], **kw)
        try:
            client.admin.command("ping")      # a client connects lazily: fail here
        except Exception:
            client.close()
            raise
        return MongoConn(client, client[entry["database"]])

    def session(self, conn, readonly):
        # MongoDB has no read-only session. A read command sends only the
        # reads in commands/ (the suite holds them to it); a user holding
        # only the `read` role is the line the server keeps (doctor says so).
        return conn

    def close(self, conn):
        try:
            conn.rollback()
        finally:
            conn.client.close()

    def connect_failure(self, exc, conn_name, entry):
        """Name the next step for the failures MongoDB and pymongo diagnose."""
        message = str(getattr(exc, "details", None) and exc.details.get("errmsg") or exc)
        low = message.lower()
        who = entry.get("user") or "<the user>"
        head = f"Could not connect using connection {conn_name!r}: {message}"
        if getattr(exc, "code", None) == 18 or "authentication failed" in low:
            return (f"{head}\nAuthentication failed for {who}: a wrong password, or "
                    "the user lives in another database than the one authenticated "
                    f"against — set \"auth_source\" (default \"admin\") in {CONFIG_REL}.")
        if "ssl" in low or "tls" in low or "certificate" in low:
            return (f"{head}\nThe TLS handshake failed. Set \"tls\": true only when "
                    "the server requires TLS, and check that this machine trusts "
                    "its certificate.")
        if type(exc).__name__ == "ServerSelectionTimeoutError" or "timed out" in low \
                or "connection refused" in low:
            return (f"{head}\nNothing answered at {self.target_of(entry)}. Check host "
                    "and port. A replica set member reached through another address "
                    "(a container, a tunnel) needs \"direct\": true, or "
                    "\"replica_set\" and the names its members advertise.")
        return (f"{head}\nCheck host/port/database, the credentials, and that the "
                "server is reachable from here. Use --conn NAME to try a different "
                "entry.")

    def schema_of(self, entry):
        # a database name is case-sensitive, and kept as written
        return str(entry.get("database") or "")

    def target_of(self, entry):
        host = str(entry.get("host") or "")
        if not host:
            return ""
        if ":" not in host and "," not in host:
            host = f"{host}:{entry.get('port') or self.default_port}"
        return f"{host}/{entry['database']}" if entry.get("database") else host

    # --- what check asks --------------------------------------------------------

    def server_version(self, conn):
        version = run(conn, "server-build.json").get("version")
        hello = run(conn, "server-hello.json")
        if hello.get("msg") == "isdbgrid":
            role = "mongos, a sharded cluster"
        elif hello.get("setName"):
            state = ("primary" if hello.get("isWritablePrimary") else
                     "secondary: reads only" if hello.get("secondary") else "not primary")
            role = f"replica set {hello['setName']}, {state}"
        else:
            role = "standalone"
        return f"MongoDB {version} ({role}) — database {conn.db.name}"

    def floor_warning(self, conn):
        """Below MongoDB 7.0, the oldest version CI tests: said by `check`,
        never refused (pythia-core DESIGN.md §8, question 2)."""
        build = run(conn, "server-build.json")
        array = build.get("versionArray") or [
            int(p) for p in str(build.get("version", "0.0")).split(".")[:2] if p.isdigit()]
        major_minor = tuple((list(array) + [0, 0])[:2])
        if major_minor >= FLOOR:
            return None
        return (f"MongoDB {major_minor[0]}.{major_minor[1]} is below pythia-mongo's "
                "floor, 7.0: it is not tested there (CI runs 7.0 and 8.0), and "
                "MongoDB no longer supports it. Most commands may still work.")

    def current_schema(self, conn):
        # no search path: every name lands in the database the connection names
        return conn.db.name

    # --- the read tier (read.py) -------------------------------------------------

    def object_names(self, conn, schema, pattern, fetch):
        return read.object_names(conn, schema, pattern, fetch)

    def source(self, conn, schema, name):
        return read.source(conn, schema, name)

    def columns(self, conn, schema, name):
        return read.columns(conn, schema, name)

    def ddl(self, conn, schema, name):
        return read.ddl(conn, schema, name)

    def grep(self, conn, schema, text, fetch):
        return read.grep(conn, schema, text, fetch)

    def dependencies(self, conn, schema, name, depth):
        return read.dependencies(conn, schema, name, depth)

    def dependents(self, conn, schema, name, depth):
        return read.dependents(conn, schema, name, depth)

    def compile_errors(self, conn, schema, name):
        return read.compile_errors(conn, schema, name, self.driver_errors())

    # --- the write tier (write.py) -----------------------------------------------

    def classify(self, text):
        return write.classify(text)

    def prepare_statement(self, text, group):
        return write.prepare_statement(text, group)

    def parse_object(self, stmt, group):
        return write.parse_object(stmt, group)

    def destructive_reason(self, stmt, group):
        return write.destructive_reason(stmt, group)

    def dml_probe(self, stmt):
        return write.dml_probe(stmt)

    def measure_row_set(self, conn, target, pred):
        return write.measure_row_set(conn, target, pred)

    def snapshot(self, conn, schema, group, ident):
        return write.snapshot(conn, schema, group, ident)

    def rehearse(self, conn, schema, group, stmt, ident, snapshot):
        return write.rehearse(conn, schema, group, stmt, ident, snapshot,
                              self.driver_errors())

    def restore_statement(self, group, ident, before, outcome):
        return write.restore_statement(group, ident, before, outcome)

    def privilege_warning(self, conn, schema):
        return write.privilege_warning(conn, schema)

    # --- the predict tier (write.py) ----------------------------------------------

    def execute(self, conn, schema, group, stmt, ident):
        return write.execute(conn, schema, group, stmt, ident, self.driver_errors())

    def verify_written(self, conn, schema, group, stmt, ident, outcome):
        return write.verify_written(conn, schema, group, stmt, ident, outcome,
                                    self.driver_errors())

    # --- the release tier (write.py) ---------------------------------------------

    def split_script(self, text):
        return write.split_script(text)

    # --- the lint tier (rules.py) ------------------------------------------------

    def lint_rules(self):
        from . import rules
        return list(rules.RULES)

    # --- the harness tier (guard.py) ---------------------------------------------

    def raw_client_pattern(self):
        return guard.CLIENTS

    def write_sql_pattern(self):
        return guard.WRITE_SQL

    def script_pattern(self):
        return guard.SCRIPT

    def connections_template(self):
        return copy.deepcopy(guard.TEMPLATE)

    def skills_dir(self):
        return guard.SKILLS_DIR

    def mcp_tool_pattern(self):
        return guard.MCP_TOOLS

    def mcp_write_tool_pattern(self):
        return guard.MCP_WRITE_TOOLS

