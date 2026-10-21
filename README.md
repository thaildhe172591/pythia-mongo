# pythia-mongo

**English** · [Tiếng Việt](https://github.com/thaildhe172591/pythia-mongo/blob/main/README.vi.md)

pythia for MongoDB: database development for AI agents, built on
[pythia-core](https://github.com/thaildhe172591/pythia-core). It aims to do
what [pythia](https://github.com/thaildhe172591/pythia) does on Oracle,
[pythia-postgres](https://github.com/thaildhe172591/pythia-postgres) on
PostgreSQL and [pythia-mssql](https://github.com/thaildhe172591/pythia-mssql)
on SQL Server: the agent learns from the live database, asks a person before
any write, and writes only through a gate that snapshots, verifies and
reports honestly.

**Alpha (0.1.0).** It reads everything pythia's Learn movement needs, writes through one gate — data rehearsed in a transaction;
validators, views and indexes predicted, written once, and read back — and
wires a project for an agent: the guard, the session brief, the approval
doors and the `pythia-mongo-*` skills.

| Works today |
|---|
| reads: `check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact`, `errors`, `connections` |
| writes: `apply`, `deploy`, `approve`, `journal`, `history`, `policy`, `autopilot`, `lint` |
| the harness: `install`, `doctor`, `hook`, `mcp`, `skill lint` |

MongoDB 7.0 and 8.0 are tested; 7.0 is the floor.

## Install

```bash
pip install pythia-mongo
```

That brings pythia-core, and [pymongo](https://pypi.org/project/pymongo/),
the only driver it uses. The development version is the main branch of
both:

```bash
pip install "git+https://github.com/thaildhe172591/pythia-core" \
            "git+https://github.com/thaildhe172591/pythia-mongo"
```

## Set up a project for an agent

```bash
cd your-project
pythia-mongo install     # once; a second run changes nothing
pythia-mongo doctor      # is everything wired? exit 1 names what is not
```

`install` writes, and leaves everything else as it was:

- `.pythia/mongo/connections.json`, mode 600, created once from the
  template — the developer fills in the passwords; an agent never opens it;
- `.gitignore` lines for that file, this machine's approvals
  (`.pythia/mongo/grants/`) and `.claude/settings.local.json`;
- `.claude/settings.local.json`: the hooks (the guard, the session brief,
  the AskUserQuestion answer), spelled with this interpreter's absolute path
  so they start whether or not a virtual environment is active, and deny
  rules for the engine's files;
- the MCP approver `pythia_mongo` (tool `pythia_mongo_approve`), in this
  machine's files only: Claude Code's local scope for the project
  (`~/.claude.json`) and Codex's `~/.codex/config.toml`, each when that
  client has run here;
- a `pythia-mongo` block in CLAUDE.md and AGENTS.md (other tools' blocks,
  and the developer's own text, are left alone);
- the skills, in `.claude/skills` and `.agents/skills`:
  `using-pythia-mongo` (the router), `pythia-mongo-explore`,
  `pythia-mongo-impact`, `pythia-mongo-apply`, `pythia-mongo-deploy`,
  `pythia-mongo-autopilot`, `pythia-mongo-verify`.

Restart the agent's session after installing, so the hooks load. Each
session then starts with the rules and a `STATE` line (connections, the
write policy). Before every tool call the guard decides:

| The agent runs | The guard |
|---|---|
| `mongosh` or the legacy `mongo` given a write (`insertOne`, `updateMany`, `deleteMany`, `replaceOne`, `drop`, `createIndex`, `createView`, `renameCollection`, `bulkWrite`, `runCommand`, `adminCommand`, `createUser`, a `$out` or `$merge` stage, `load()`), or a script (`-f`, `--file`, a `.js` or `.mjs` file, `< file`, a pipe into the shell); `mongoimport`, `mongorestore`, `mongofiles` — also behind `docker exec`, `ssh`, `sudo` or `bash -c` | denies: writes go through `pythia-mongo apply` |
| a MongoDB MCP server's tool named for a write (`insert-many`, `update-many`, `delete-many`, `drop-collection`, `create-index`, `rename-collection`, ...), or given a command document that writes (`{"drop": ...}`, `{"collMod": ...}`, a `$merge` or `$out` stage) | denies |
| reading `connections.json`; editing `policy.json`, the journal or a grant; setting `PYTHIA_MONGO_CI`; calling `grants.mint` from a one-liner | denies |
| a `pythia-mongo` read, a preview, `approve --card` | allows without a prompt |
| `apply --confirm <token>` the developer already approved on this connection | allows; apply re-verifies it |
| `mongosh` reads, `mongodump`, `mongoexport`, `approve`, `--yes`, `policy set`, anything compound | stays out: the client asks |

The guard reads a command for what it names, not what it means: it can
deny a harmless command (a `find` that mentions `.drop(` in a string, or a
`runCommand` that only reads) and miss a write spelled in a way it does not
list. It sees the commands Claude Code hands its tools, not Compass or a
driver inside the application. The gate behind it holds either way
(pythia-core's SECURITY.md).

pythia-postgres and pythia-mssql install beside it in one project, and
pythia for Oracle too: each keeps the others' hooks and instruction blocks,
and each guard and approval hook acts for its own tool only (pythia-core's
CI checks it with all four installed).

## Connections

`.pythia/mongo/connections.json` in the project root, owner-readable only
(`chmod 600`), and out of git. Template:
[examples/connections.example.json](https://github.com/thaildhe172591/pythia-mongo/blob/main/examples/connections.example.json).

```json
{
  "default": "dev",
  "dev": { "host": "db-dev", "port": 27017, "database": "app",
           "user": "app_agent", "password": "...", "auth_source": "admin",
           "tls": false }
}
```

- `host` and `database` are required. `host` may list several members
  (`"a:27017,b:27017"`).
- `auth_source` is the database the user lives in (default `admin`).
- `tls` (default `false`), `replica_set`, and `direct` (`true` talks to the
  one member named, not the set it advertises — for a member reached
  through a container's mapped port or a tunnel).
- A connection string (`"uri"`) is refused: it carries the password into
  every place it is printed.
- The entry is picked by `--conn NAME`, then `PYTHIA_MONGO_CONNECTION`,
  then the only entry, the folder directly under the project root, then
  `"default"`. `PYTHIA_MONGO_CONFIG` points at another file.

pythia for Oracle keeps `.pythia/connections.json`, and the other engines
their own folders; pythia-mongo reads none of them.

## Commands

```bash
pythia-mongo check                 # server, replica set or not, database
pythia-mongo ls "t_order%"         # collections and views by LIKE pattern
pythia-mongo src t_order           # a validator, or a view's pipeline, as Extended JSON
pythia-mongo cols t_order          # fields and their types, from a sample of documents
pythia-mongo ddl t_order           # the commands that make it: create, createIndexes
pythia-mongo grep PAID             # every validator and pipeline line holding a text
pythia-mongo deps v_order_lines    # what a view reads
pythia-mongo impact t_order        # what reads it: run before changing it
pythia-mongo errors [NAME]         # documents a validator rejects, views that fail
```

`--json` gives one envelope per command; `--limit`, `--max-lines` and
`--offset` window long output, and any truncation says how to fetch the
rest.

### What MongoDB cannot see, and how pythia-mongo says so

- **There is no catalog of dependencies.** MongoDB records only views:
  `impact` walks every view's `viewOn` and the collections its pipeline
  reads (`$lookup`, `$graphLookup`, `$unionWith`, `$facet`, nested
  pipelines too). The application code that reads and writes a collection
  through a driver is invisible to the database, and so are views in other
  databases, scheduled `$merge` / `$out` jobs and change streams. Each
  blind spot is printed every time.
- **There is no column list.** `cols` reads up to 1000 sampled documents:
  each field path (`address.city`, `tags[]` for an array's elements), its
  types by how many documents hold them, how many hold it at all, and what
  the `$jsonSchema` validator says (required, description). A field the
  validator declares and no sampled document holds is listed as `0 of N`.
  When the collection holds more than the sample, it says so.
- **`errors` counts, it does not compile.** For each collection with a
  validator: how many documents break it as it stands, with the first of
  them (`warning` when the validator only warns). Each view runs over its
  first 100 documents, and a view that reads a collection that does not
  exist is named. A collection without a validator has nothing to check,
  and the output says `NOT VERIFIED`.
- **`ddl` is rebuilt, not dumped:** a JSON array of the command documents
  that make the collection (`create` with its validator and options,
  `createIndexes`) or the view. The live check drops each, runs them,
  rebuilds and compares.
- **Reads never write, and the server is the second line.** MongoDB has no
  read-only session. Every command a read sends is a file in
  `src/pythia_mongo/commands/`, and the suite holds them to reads only; a
  user holding only the `read` role is what the server enforces.

### Writing: the gate

```bash
pythia-mongo apply change.json                   # preview: rehearsed or predicted, nothing kept
pythia-mongo approve 3fa9c1                      # the developer approves, at their own console
pythia-mongo apply change.json --confirm 3fa9c1  # writes it — only as approved
pythia-mongo journal restore <entry>             # undo is a write too: preview, approve, confirm
pythia-mongo policy                              # which groups may be written, and is rollback real?
```

The developer approves through the first door that works:

1. **In Claude Code's chat.** The agent asks with AskUserQuestion, its text
   exactly the output of `pythia-mongo approve --card <token>`, options
   Approve / Reject. The answer hook records the approval only when the
   question carried that card and the developer chose Approve themselves —
   not an answer the agent wrote, not a dialog that closed unattended.
2. **Through the MCP approver** (`pythia_mongo_approve`; Codex starts
   here): the client shows the card, and only an explicit Approve counts.
3. **At the developer's console:** `pythia-mongo approve <token>`.

`pythia-mongo doctor` warns about settings that would answer the chat door
for the developer (`dontAsk` mode, an allow rule for AskUserQuestion, a hook
matching every tool).

A file holds **one command document**, in Extended JSON — the document
MongoDB itself takes, not mongosh JavaScript:

```json
{"update": "t_order",
 "updates": [{"q": {"status": "DRAFT"}, "u": {"$inc": {"total": 1}}, "multi": true}]}
```

`apply` sorts it into a group, and the policy decides: `source` — a view
(`create` with `viewOn`, `collMod` of `viewOn` and `pipeline`) or a
validator (`collMod` of `validator`, `validationLevel`,
`validationAction`) — needs the developer's approval; `structural` (a new
collection, `createIndexes`, `dropIndexes`, `drop`, other `collMod`
options) and `data_dml` (`insert`, `update`, `delete`) are denied until the
developer runs `pythia-mongo policy set <group> confirm` at a console.

**Data is rehearsed.** An insert, update or delete runs inside a
transaction and is aborted: the preview shows how many documents it
touched, and an UPDATE or DELETE is approved on its documents — the count, a
sample, and a fingerprint (`$toHashedIndexKey` over each document). If one
joins, leaves or changes before the confirm, the confirm is refused. A
document the validator rejects fails the rehearsal (MongoDB reports it in
the reply, not as an error, and pythia-mongo reads the reply).
Transactions need a replica set: on a standalone server data writes are
refused — a single-node replica set is enough for development.

**Everything else is predicted.** MongoDB runs a view, a validator, an
index or a dropped collection outside any transaction, so nothing can be
run and rolled back. pythia-core's predict tier takes over: nothing runs
before the approval, and the preview says "predicted — nothing ran".

| Command | The prediction | Read back after the write |
|---|---|---|
| a validator (`collMod`) | counts the documents the new validator would reject, with the first of them; a validator MongoDB would refuse has nothing to approve | the validator as stored, and the count again — a different count exits 3 |
| a view (`create`, `collMod`) | runs the pipeline over no documents (would MongoDB accept it?) and until its first 100 documents (does it run?); names what it reads that does not exist; runs every view built on it on top of the new pipeline | the view as stored, and every run again — a failure the prediction did not see exits 3 |
| a unique index | looks for the keys it would meet twice (its partial filter or sparse rule applied); duplicates mean nothing to approve | each index is there, with its key |
| an index, a drop | an index name that exists with another key is refused; a drop names every view that reads what it drops | the index is there, or gone |

After the approval core runs the command once. MongoDB applies each of
these commands whole or not at all, so a refusal wrote nothing and keeps
the approval; a command whose answer never came is reported `WRITTEN?`
(exit 3). What landed is read back, and anything unlike the prediction is
reported and exits 3 with the restore. A prediction runs for at most 30
seconds (`maxTimeMS`).

**Refused, with the reason:** mongosh JavaScript, several commands in one
file, a key written twice, JavaScript anywhere (`$where`, `$function`,
`$accumulator`, code), `$out` and `$merge` (a prediction runs a pipeline
before approval: it must never write), reads (`aggregate`, `find`),
`findAndModify`, an upsert, an update or delete of one document among many
(`"multi": true` or `"limit": 0`, or name it by `_id`), users and roles,
`renameCollection`, `dropDatabase`, `bypassDocumentValidation`, session and
transaction fields (`lsid`, `writeConcern`, ...), and `system.` collections.

### A release: `deploy`, one transaction

```bash
pythia-mongo deploy 01_fix.json 02_backfill.json                     # preview the release as one transaction
pythia-mongo deploy 01_fix.json 02_backfill.json --confirm 9c41e0b2aa  # all of it, as approved, or none
```

A release is data: one or more files, each one command document or a JSON
array of them, in the order they run. It is rehearsed in one transaction —
each command in order, its documents counted and fingerprinted at its own
point (an update of a document the release inserts sees it), then
everything is aborted. One card shows every command, and one approval (a
10-digit token, through the same doors) covers the release; a single
command's token cannot be approved alone. The confirm checks that every
command is byte-identical to what was approved before anything runs,
re-runs the release in one transaction, and commits only if every command
still matches. A command that fails, or documents that moved, abort the
whole release. A commit that does not answer is reported `WRITTEN?` for the
whole release.

A validator, a view, an index or a new or dropped collection has no place in
a release: MongoDB runs them outside any transaction, so they are predicted,
not rehearsed, and could not land all or nothing. `deploy` refuses them
before anything is written; apply each on its own. Anything `apply` refuses
is refused here too.

### Lint: before any apply

```bash
pythia-mongo lint 01_fix.json 02_view.json   # a change's files in one run
pythia-mongo lint --rules                    # every rule and its effective severity
```

The rules read what MongoDB accepts and a reviewer would not:

| Rule | Default | Why |
|---|---|---|
| `mongo-validation-warn` | warn | `validationAction: "warn"` writes every document that breaks the validator anyway, and only logs it |
| `mongo-validation-off` | warn | `validationLevel: "off"` keeps the validator and enforces nothing |
| `mongo-validator-required` | info | a `$jsonSchema` with no `required` list accepts a document that holds none of its fields |
| `mongo-collection-validator` | warn | a new collection gets its validator in the same change (a `collMod` of it that sets one counts) |
| `mongo-unique-optional` | warn | a unique index counts every document without the field as `null`, and refuses the second — make it partial (`$exists`) or sparse |
| `mongo-ttl` | warn | a TTL index deletes documents on the server's schedule, unasked and unjournaled |
| `mongo-update-replacement` | warn | an update whose `u` holds no operator replaces each document, removing every field it does not name |

What MongoDB refuses itself is left to the rehearsal or the prediction. The
team sets severities and naming patterns (a view's name, `VIEW`; a
validator's collection, `VALIDATOR`) in `.pythia/mongo/lint.json`:

```json
{"severity": {"mongo-validation-warn": "error", "naming": "error"},
 "naming": {"VIEW": "^v_[a-z0-9_]+$"}}
```

Every preview shows the findings, a command's errors are on its card, and
autopilot never lands a lint error.

### Autopilot: one lease instead of every approval

```bash
pythia-mongo autopilot request --groups source --hours 2 --max-writes 30
pythia-mongo autopilot report      # every write under the lease, with its restore
pythia-mongo autopilot off         # anyone may revoke
```

When the developer wants the agent to work without approving each write,
the agent requests a lease. Its card names the connection, the groups, the
time, the number of writes and whether destructive commands are included,
and nothing is delegated until the developer approves it through a door (or
runs `pythia-mongo autopilot on` at a console). While it lasts, `apply` and
`deploy` land what it covers without `--confirm` — still snapshotted,
rehearsed or predicted, read back and journaled. It never covers another
connection, one marked `"protected": true` (or an `"env"` of prod /
production / prd / live), a group or destructive command the card did not
name, or more than 1000 documents; a write that breaks something, lands
unlike its prediction or is `WRITTEN?`, or five failures in a row pause it.

### Least privilege

The read commands need the `read` role on the database. Writing needs
`readWrite` (data, indexes, new collections and views) and `dbAdmin`
(`collMod` of a validator or a view); the preview warns when the user holds
far more (`root`, `dbOwner`, any `AnyDatabase` role). The live check runs
every read as a `read` user, and every write as one holding `readWrite` and
`dbAdmin`.

## Every command is a file

Like the SQL engines' query files, every command pythia-mongo sends lives in
`src/pythia_mongo/commands/` as JSON: what it is for, its binds, what it
returns, and the command document. A bind is written `{"$bind": "name"}`
where its value goes, so text from a person or an agent always lands as a
value — never as an operator, a stage or a command of its own. The suite
checks that every file declares exactly the binds it uses, holds no
JavaScript (`$where`, `$function`, `$accumulator`), and holds no write,
`$out` or `$merge`: every command file reads. The only write pythia-mongo
ever sends is the developer's own command document — in a rehearsal's
transaction, or once after the approval.

## Tests

```bash
python tests/test_mongo.py    # no database, no pymongo — mutation-checked
python tests/live_check.py    # a disposable server only (see its docstring)
```

CI runs the suite on Ubuntu, Windows and macOS, Python 3.9 and 3.13, and
the live check — every read, every write path, a release, a lint finding
in a real preview and a write under a lease — against MongoDB 7.0 and 8.0,
each a single-node replica set with authentication. It tests against the
pythia-core branch of the same name when one exists.

## License

MIT
