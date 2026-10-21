"""MongoDB, through pymongo, as a pythia-core engine.

It answers the connect tier (here) and the read tier (read.py). MongoDB
has no SQL and no catalog of dependencies: what it keeps is read as command
documents (catalog.py), and what it cannot see — the application code
around it — is said in every answer that depends on it.
"""
import sys

from . import __version__, read
from .catalog import run

CONFIG_REL = ".pythia/mongo/connections.json"
REQUIRED = ("host", "database")


class MongoConn:
    """One client and the database a connection names."""

    def __init__(self, client, db):
        self.client, self.db = client, db

    def run(self, name, command, cursor, admin):
        db = self.client.admin if admin else self.db
        if cursor:
            return list(db.cursor_command(command))
        return db.command(command)


class MongoEngine:
    name = "mongo"
    label = "MongoDB"
    command = "pythia-mongo"
    env_prefix = "PYTHIA_MONGO"
    version = __version__
    bind_style = "document"
    default_port = 27017

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
