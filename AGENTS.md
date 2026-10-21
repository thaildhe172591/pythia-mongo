# Working in this repository / with this tool

pythia-mongo is pythia for MongoDB, on pythia-core. It is pre-alpha: it
reads everything pythia's Learn movement needs, and writes through one
gate. `pythia-mongo install` wires a project: the guard, the session brief
and the `pythia-mongo-*` skills (`using-pythia-mongo` routes).

## Using pythia-mongo as an agent (Phase 5c)

1. **Ask the database, never the dump.** `ls`, `src`, `cols`, `ddl`, `grep`
   against the live database. A collection has no column list: `cols`
   reads a sample, and says so when the collection holds more than it read.
2. **Lint before apply.** `pythia-mongo lint <files>` — a change's files in
   one run. Errors are fixed, not argued; the team's `.pythia/mongo/
   conventions.md`, when it exists, is read before writing any command.
3. **Impact before change.** Run `pythia-mongo impact <NAME>` before
   proposing any modification. MongoDB records only views: the application
   code that reads and writes a collection is invisible to it, so search
   the code too. Relay every `blind spot` line, and never call an impact
   list complete — for MongoDB it never is. When it prints `! show this
   list to the developer`, show the developer the list before writing
   anything.
4. **Writes go through `pythia-mongo apply` (one command document per file)
   or `pythia-mongo deploy` (a data release, one transaction) only.** A
   file holds Extended JSON — the document MongoDB takes, never mongosh
   JavaScript. Never write through `mongosh`, `mongoimport`,
   `mongorestore`, Compass, a MongoDB MCP server's write tools or a driver
   script: those have no snapshot, no rehearsal or prediction, and no
   journal. Where `pythia-mongo install` wired the hooks, the guard denies
   them; where it did not, this rule still binds. No `STATE` line at
   session start means the hooks are not running: say so, and ask the
   developer to run `pythia-mongo doctor`.
5. **The developer sees every preview.** Relay `apply`'s preview verbatim:
   the diff, the rehearsal or the prediction (what would break, or NOT
   VERIFIED), the documents, the destructive warning, the lint findings.
   Then ask through the first door that works, moving to the next unasked
   when one fails: on Claude Code an `AskUserQuestion` whose text is the
   output of `pythia-mongo approve --card <token>` verbatim (options
   Approve / Reject); then the `pythia_mongo_approve` tool (MCP — where
   Codex starts); then the developer's terminal, `pythia-mongo approve
   <token>`. Pass `--confirm <token>` only after the approval arrives.
   `--yes` and loosening `policy` are the developer's actions, at a
   console.
6. **"Predicted — nothing ran" is a prediction, and is said as one.** A
   view, a validator, an index or a drop cannot be rehearsed in MongoDB:
   the preview predicts it from the data as it stands, and the write is
   read back after. Never call a prediction a rehearsal, and never call an
   approved write "verified" before its report.
7. **Autopilot is the developer's delegation, not yours.** When they want
   you to work without per-write approvals, request the narrowest lease
   that fits (`pythia-mongo autopilot request`) and ask once through a
   door. Inside it, covered writes land without asking; outside it, the
   normal gate applies. A paused lease means stop and show the developer.
   Report every write with `pythia-mongo autopilot report`.
8. **Scope is what was asked.** Dependents that break are reported with a
   proposal, never fixed on your own initiative.
9. **Exit codes are the verdict:** `0` clean · `1` refused (relay the
   reason; do not route around it) · `3` written but broken, written but
   unlike the prediction, or `WRITTEN?` — never report success; show the
   report and the printed restore command. Never read `$?` through a pipe.
10. **Restores are writes.** `journal restore` previews and needs the same
    approval as any apply.
11. **"Not verified" is said plainly.** `errors` counts the documents each
    validator rejects and runs each view over its first documents; a
    collection without a validator is named as unchecked. Never report a
    `NOT VERIFIED` line as "no errors".
12. **Truncation is always announced.** If output has no truncation marker,
    you saw everything. If it has one, say so or fetch the rest with
    `--offset`.
13. **Never open `.pythia/mongo/connections.json`, or anything under
    `.pythia/mongo/grants/`.** The first holds passwords;
    `pythia-mongo connections` lists the names, users, databases and
    targets without them. A grant written by anyone but `approve` is a
    forged approval.

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
  JavaScript anywhere; no write, `$out` or `$merge` in any command file —
  the only write sent is the developer's own document. A prediction is
  bounded by `maxTimeMS`. MongoDB 7.0 is the floor.
- **Dependencies:** pythia-core and pymongo, nothing else (a test enforces
  it).
- **Engine-neutral logic goes to pythia-core.** If an answer would be the
  same on PostgreSQL or SQL Server, it does not belong here (DESIGN.md §3).
- **Skills:** `src/pythia_mongo/skills/<name>/SKILL.md`, `name` = folder,
  prefixed `pythia-mongo-` (or `using-pythia-mongo`), description opening
  with `Use when` / `Use before`, a `**Phase:**` line, at most 150 lines
  (detail in `reference/`), and a row in `using-pythia-mongo`'s routing
  table. A test holds every one to it.
- **Docs never contradict code:** a behaviour change updates the docstring,
  README.md, CHANGELOG.md and the affected skill in the same change.
- **Versions** agree in pyproject.toml and `pythia_mongo.__version__`.

## Never

- Read or write pythia for Oracle's files (`.pythia/connections.json`,
  `.pythia/journal/`) or another engine's (`.pythia/postgres/`,
  `.pythia/mssql/`), or take their commands or variables.
- Point the live check at a shared server: it creates a user and drops a
  database.
- Field-test `pythia-mongo install` inside this repository:
  `src/pythia_mongo/skills/` is the source pack. Use a scratch directory.
- Put real-world identifiers anywhere (hosts, schemas, tenants,
  credentials). Examples use APP_OWNER, PKG_ORDER, T_ORDER. Everything
  shipped is English.
