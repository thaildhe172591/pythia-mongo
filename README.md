# pythia-mongo

pythia for MongoDB: database development for AI agents, built on
[pythia-core](https://github.com/thaildhe172591/pythia-core). It aims to do
what [pythia](https://github.com/thaildhe172591/pythia) does on Oracle,
[pythia-postgres](https://github.com/thaildhe172591/pythia-postgres) on
PostgreSQL and [pythia-mssql](https://github.com/thaildhe172591/pythia-mssql)
on SQL Server: the agent learns from the live database, asks a person before
any write, and writes only through a gate that snapshots, verifies and
reports honestly.

**Pre-alpha (Phase 5a).** It reads everything pythia's Learn movement
needs, and writes nothing yet.

| Works today | Next |
|---|---|
| `check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact`, `errors`, `connections` | the write gate (5b): data rehearsed in a transaction; validators, indexes and views predicted, written and verified; then the harness and skills (5c) |

MongoDB 7.0 and 8.0 are tested; 7.0 is the floor.

## Install (from git while pre-alpha)

```bash
pip install "git+https://github.com/thaildhe172591/pythia-core" \
            "git+https://github.com/thaildhe172591/pythia-mongo"
```

That brings [pymongo](https://pypi.org/project/pymongo/), the only driver
it uses.

## Connections

`.pythia/mongo/connections.json` in the project root, owner-readable only
(`chmod 600`), and out of git. Template:
[examples/connections.example.json](examples/connections.example.json).

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

### Least privilege

The read commands need the `read` role on the database. The live check runs
every read command as such a user.

## Every command is a file

Like the SQL engines' query files, every command pythia-mongo sends lives in
`src/pythia_mongo/commands/` as JSON: what it is for, its binds, what it
returns, and the command document. A bind is written `{"$bind": "name"}`
where its value goes, so text from a person or an agent always lands as a
value — never as an operator, a stage or a command of its own. The suite
checks that every file declares exactly the binds it uses, holds no
JavaScript (`$where`, `$function`, `$accumulator`), and that a read command
holds no write, `$out` or `$merge`.

## Tests

```bash
python tests/test_mongo.py    # no database, no pymongo
python tests/live_check.py    # a disposable server only (see its docstring)
```

CI runs the suite on Ubuntu, Windows and macOS, Python 3.9 and 3.13, and
the live check against MongoDB 7.0 and 8.0, each a single-node replica set
with authentication. It tests against the pythia-core branch of the same
name when one exists.

## License

MIT
