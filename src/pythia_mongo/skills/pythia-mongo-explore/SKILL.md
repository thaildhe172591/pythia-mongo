---
name: pythia-mongo-explore
description: Use when explaining, investigating or reading MongoDB - what a collection's documents look like, what a validator allows, what a view returns, why documents are rejected. Asks the live database through pythia-mongo read commands, never a dump, a sample file or memory.
---

# Explore the live database

**Announce at start:** "Using pythia-mongo-explore to read the live database."

**Phase:** Learn — facts from the database, before any opinion

MongoDB has no schema file to trust: documents drift field by field, a
validator is changed in Compass, an index is added by hand. An explanation
built on yesterday's export explains a database that does not exist.

## The Iron Law

```
EVERY FACT COMES FROM THE LIVE DATABASE, WITH THE COMMAND THAT SHOWED IT
```

## The commands

| Question | Command |
|---|---|
| Where am I — replica set or standalone, which database? | `pythia-mongo check` |
| Which collections and views match a name? | `pythia-mongo ls "t_order%"` |
| What does this validator allow, this view do? | `pythia-mongo src <name>` |
| What do its documents hold — fields, types, how many have each? | `pythia-mongo cols <name>` |
| What commands would make it, indexes included? | `pythia-mongo ddl <name>` |
| Where is this text in a validator or a pipeline? | `pythia-mongo grep <text>` |
| What does a view read? | `pythia-mongo deps <name>` |
| What reads it? | `pythia-mongo impact <name>` (see `pythia-mongo-impact`) |
| Which documents break their validator, which views fail? | `pythia-mongo errors [<name>]` |

`--json` gives structured output on every command.

## Reading the output honestly

- **`cols` reads a sample.** Up to 1000 documents: a field few documents
  hold may be missing, and a `-- blind spot:` line says when the collection
  holds more than was read. A field the validator declares that no sampled
  document holds shows `0 of N`.
- **Truncation is announced.** No `-- truncated` line means you saw
  everything. With one, say so, or fetch the rest with `--offset`.
- **`-- blind spot:` lines are part of the answer.** MongoDB records only
  views: application code, other databases and `$merge` jobs are never
  seen. Relay them; never call a list complete when one is printed.
- **`errors` counts documents, it does not compile anything.** A
  collection without a validator is named as unchecked, and each view runs
  over its first documents only — `NOT VERIFIED` is never "no errors".

## Red flags

| Thought | Reality |
|---------|---------|
| "The model class shows the fields" | The documents may not. `pythia-mongo cols`. |
| "`errors` printed nothing, so it is clean" | Only if no NOT VERIFIED line was printed. |
| "I'll open connections.json to see the host" | Never: `pythia-mongo connections` lists it without passwords. |
| "I'll check it in mongosh quickly" | Read commands answer it, with sampling and blind spots said. |

## Hand-off

Explaining only → done, with the commands quoted. A change follows →
`pythia-mongo-impact` before anything is written.
