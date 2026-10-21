# Working in this repository / with this tool

pythia-mongo is pythia for MongoDB, on pythia-core. It is pre-alpha
(Phase 5a): it reads everything pythia's Learn movement needs, and writes
nothing yet.

## Using pythia-mongo as an agent (Phase 5a)

1. **Ask the database, never the dump.** `ls`, `src`, `cols`, `ddl`, `grep`
   against the live database. A collection has no column list: `cols`
   reads a sample, and says so when the collection holds more than it read.
2. **Impact before change.** Run `pythia-mongo impact <NAME>` before
   proposing any modification. MongoDB records only views: the application
   code that reads and writes a collection is invisible to it. Relay every
   `blind spot` line, and never call an impact list complete — for
   MongoDB it never is. When it prints `! show this list to the developer`,
   show the developer the list before writing anything.
3. **"Not verified" is said plainly.** `errors` counts the documents each
   validator rejects and runs each view over its first documents; a
   collection without a validator is named as unchecked. Never report a
   `NOT VERIFIED` line as "no errors".
4. **Truncation is always announced.** If output has no truncation marker,
   you saw everything. If it has one, say so or fetch the rest with
   `--offset`.
5. **It writes nothing yet, so neither do you through it.** Until `apply`
   exists (Phase 5b), propose a change as a command document and let the
   developer run it. Never write through `mongosh`, `mongoimport`,
   `mongorestore` or a driver script on pythia-mongo's behalf.
6. **Never open `.pythia/mongo/connections.json`.** It holds passwords.
   `pythia-mongo connections` lists the names, users, databases and targets
   without them.
7. **Exit codes are the verdict:** `0` clean, `1` refused. Relay the reason;
   do not route around it. Never read `$?` through a pipe.

## Changing pythia-mongo itself

- Run the suite before calling a change done: `python tests/test_mongo.py`
  (no database, no pymongo). Against a disposable server, also
  `python tests/live_check.py`. TDD: the failing test comes first.
- CI runs Ubuntu, Windows and macOS on Python 3.9 and 3.13: build paths with
  `pathlib` / `os.path.join`, and use no stdlib API newer than 3.9.
- **Commands:** every command pythia-mongo sends lives in
  `src/pythia_mongo/commands/`, one per file: `purpose`, `binds`, `returns`
  and `command` (and `database: "admin"` for a server command), each bind a
  `{"$bind": "name"}` value declared in the file and in `COMMAND_BINDS`. No
  JavaScript anywhere; no write, `$out` or `$merge` in a read command. MongoDB
  7.0 is the floor.
- **Dependencies:** pythia-core and pymongo, nothing else (a test enforces
  it).
- **Engine-neutral logic goes to pythia-core.** If an answer would be the
  same on PostgreSQL or SQL Server, it does not belong here (DESIGN.md §3).
- **Docs never contradict code:** a behaviour change updates the docstring,
  README.md and CHANGELOG.md in the same change.
- **Versions** agree in pyproject.toml and `pythia_mongo.__version__`.

## Never

- Read or write pythia for Oracle's files (`.pythia/connections.json`,
  `.pythia/journal/`) or another engine's (`.pythia/postgres/`,
  `.pythia/mssql/`), or take their commands or variables.
- Point the live check at a shared server: it creates a user and drops a
  database.
- Put real-world identifiers anywhere (hosts, schemas, tenants,
  credentials). Examples use APP_OWNER, PKG_ORDER, T_ORDER. Everything
  shipped is English.
