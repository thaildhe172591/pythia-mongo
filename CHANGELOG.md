# Changelog

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
