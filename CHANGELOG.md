# Changelog

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
