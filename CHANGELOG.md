# Changelog

## 0.1.1 — 2026-10-21

Phase 8 of the plan in pythia-core's DESIGN.md: the minimum version, on
pythia-core 0.1.1.

- **Below MongoDB 7.0 `check` says so** — from `buildInfo`'s
  `versionArray` — and nothing is refused. 7.0 was the floor since 0.1.0;
  CI runs the whole live check on 7.0 and 8.0.
- Asks for `pythia-core>=0.1.1,<0.2`.

## 0.1.0 — 2026-10-21

The first release, and the first on PyPI: alpha, on pythia-core 0.1.0.
Everything in the development versions below — 0.1.0.dev0 to 0.3.0.dev0,
never published — is in it.

- **Version 0.1.0**, asking for `pythia-core>=0.1.0,<0.2`.
- **README.vi.md**, the README in Vietnamese; a test holds the two to the
  same headings and the same commands.
- **`release.yml`:** a `vX.Y.Z` tag runs the suite against pythia-core's
  main, checks that pyproject.toml, `__version__` and this file name that
  version, and publishes to PyPI by trusted publishing (no token stored
  anywhere).
- **PyPI metadata:** the README as the project page, classifiers (Alpha,
  Python 3.9 to 3.13), and links to the changelog and the issues.
- **CI's live job runs on ubuntu-22.04.** MongoDB 8.0 refuses to start on
  Linux 6.19 to 7.0.13 (SERVER-121912), the kernel some ubuntu-latest
  runners now have; the job failed whenever it landed on one. A MongoDB
  server issue: pythia-mongo, as a client, is not affected.

## 0.3.0.dev0 — unreleased

Phase 5c of the plan in pythia-core's DESIGN.md: the harness, release and
lint tiers, and the skill pack, on pythia-core 0.12.0.dev0. Phase 5 is
complete.

- **The guard (`guard.py`):** `mongosh` and the legacy `mongo` given a
  write method (`insertOne`, `updateMany`, `deleteMany`, `replaceOne`,
  `drop`, `createIndex`, `createView`, `renameCollection`, `bulkWrite`,
  `runCommand`, `adminCommand`, `createUser`, ...), a `$out` or `$merge`
  stage, `load()`, or a script (`-f`, `--file`, a `.js` or `.mjs` file,
  `< file`, a pipe into the shell); `mongoimport`, `mongorestore` and
  `mongofiles` always. Denied behind `docker exec`, `ssh`, `sudo` and
  `bash -c` too; reads, `mongodump` and `mongoexport` are left to the
  client. A MongoDB MCP server's tools are named by the engine: one named
  for a write (`insert-many`, `drop-collection`, ...) is denied, and so is
  one handed a command document that writes.
- **`install`, `doctor`, `hook`, `mcp`, `skill lint`** over pythia-core,
  field-tested in a scratch project: `doctor` passes, the brief carries the
  STATE lines, the guard denies a mongosh `deleteMany` and a `$merge`
  through an MCP aggregate, and allows a pythia-mongo read.
- **`deploy`:** a data release — one command document or a JSON array of
  them per file — rehearsed and committed as one transaction under one
  approval. A validator, view, index or collection command is refused
  before anything is written: MongoDB runs it outside any transaction.
- **`lint` and seven rules:** a validator that only warns or is off, a
  `$jsonSchema` with no `required` list (a note), a new collection without
  a validator in the same change, a unique index on an optional field that
  is neither partial nor sparse, a TTL index, an update that replaces whole
  documents. Naming patterns apply to views (`VIEW`) and validators
  (`VALIDATOR`).
- **Seven skills:** `using-pythia-mongo` (the router),
  `pythia-mongo-explore`, `-impact` (the application code the database
  cannot see), `-apply` (rehearsed or predicted, with its refusals),
  `-deploy`, `-autopilot`, `-verify` — `WRITTEN?` named where it can
  appear.
- **The live check** also deploys a data release (each command seeing the
  ones before it; documents that move roll it back whole; a failing second
  command keeps nothing of the first; an index in a release is refused),
  shows a lint finding in a real preview, and lands a predicted view
  change under an autopilot lease — on MongoDB 7.0 and 8.0.

## 0.2.0.dev0 — unreleased

Phase 5b of the plan in pythia-core's DESIGN.md: MongoDB's write tier, on
pythia-core 0.11.0.dev0 and its predict tier.

- **`apply`, `approve`, `journal`, `history`, `policy`** over pythia-core's
  gate. A file holds one command document in Extended JSON.
- **Classification refuses what no group honestly fits:** mongosh
  JavaScript, several commands, a key written twice, JavaScript anywhere,
  `$out` and `$merge`, reads, `findAndModify`, upserts, an update or delete
  of one document among many, users and roles, `renameCollection`,
  `dropDatabase`, `bypassDocumentValidation`, session and transaction
  fields, `system.` collections.
- **Data is rehearsed in a transaction** (a replica set is required) and
  revalidated by a `$toHashedIndexKey` fingerprint; a document the
  validator rejects fails the rehearsal, read from the reply.
- **Views, validators, indexes and drops are predicted** — the documents a
  validator would reject, a view's pipeline run over no documents and then
  its first 100 (and every view built on it on top), the duplicates a
  unique index would meet, the views a drop would break — then run once
  after the approval and read back; anything unlike the prediction exits 3.
- **Snapshot and restore** for views and validators; a new view's undo is a
  drop. The preview warns when the user holds `root`, `dbOwner` or an
  `AnyDatabase` role.
- **The live check writes** on MongoDB 7.0 and 8.0: a validator predicted,
  approved, written and restored, and one whose prediction moved; views,
  one MongoDB refuses and one that writes; a unique index refused for its
  duplicates; data rehearsed, rows that move; a drop that breaks a view.

## 0.1.0.dev0 — unreleased

Phase 5a of the plan in pythia-core's DESIGN.md: MongoDB's connect and read
tiers, on pythia-core 0.10.0.dev0.

- **The driver is pymongo** (4.9 or later; 4.18 is the last for Python
  3.9). MongoDB 7.0 is the floor; 7.0 and 8.0 are tested.
- **Every command is a file** in `commands/`: purpose, binds, returns and
  the command document, each bind a `{"$bind": ...}` value — text from a
  person lands as a value, never as an operator. The suite holds every file
  to its declared binds, no JavaScript, and reads only in read commands.
- **`pythia-mongo check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`,
  `impact`, `errors`**, over pythia-core's command line.
- **`cols` reads a sample:** field paths, types by how many documents hold
  them, how many documents hold each field, what the `$jsonSchema` says —
  sorted, so a random sample reads the same each time — and a blind spot
  when the collection holds more than the sample.
- **`impact` walks views** (`viewOn`, `$lookup`, `$graphLookup`,
  `$unionWith`, `$facet`, nested pipelines) and names what MongoDB cannot
  see: application code, other databases, `$merge`/`$out` jobs, change
  streams.
- **`errors`** counts the documents each validator rejects (a warning when
  it only warns), runs each view over its first 100 documents, and names a
  view that reads what does not exist.
- **`ddl`** rebuilds the command documents that make a collection or view;
  the live check proves the round trip.
- **A connection string is refused** (it carries the password); `host`,
  `port`, `database`, `user`, `password`, `auth_source`, `tls`,
  `replica_set`, `direct`.
- **`tests/live_check.py`** runs every read command against a disposable
  MongoDB as a user holding only the `read` role; CI runs it on 7.0 and 8.0,
  each a single-node replica set with authentication.
