---
name: pythia-mongo-impact
description: Use before proposing or writing any change to a MongoDB collection, field, validator, index or view. Impact analysis comes first - and for MongoDB that means the views the database records and the application code it cannot see.
---

# Impact Before Change

**Announce at start:** "Using pythia-mongo-impact to measure the blast radius first."

**Phase:** Learn — and the first Ask gate: a large blast radius reaches the developer before anything is written

A renamed field breaks every service that reads it, at the next read, and
MongoDB never knew they existed: it records only views. The cost of
knowing first is one command, and one search of the code.

## The Iron Law

```
NO CHANGE PROPOSED WITHOUT ITS IMPACT MEASURED FIRST
```

## The Workflow

1. `pythia-mongo impact <name> --depth 2` — every view that reads it, as a
   tree: through `viewOn`, `$lookup`, `$graphLookup`, `$unionWith`,
   `$facet`, nested pipelines too.
2. **Search the application code.** The repository is where a collection's
   readers and writers live: search it for the collection's name, and for
   the field you are changing. Report what you found as `[code]` leads —
   the database vouches for none of it.
3. `pythia-mongo deps <name>` — for a view, what it reads.
4. `pythia-mongo errors` — the baseline. Documents that break a validator
   before the change must not be blamed on it later.

## Reading the numbers

| Result | What to do |
|---|---|
| 0 views, no code found | Say so — with both outputs — and that MongoDB cannot see other services. |
| some views, or code | List them to the developer alongside the proposal. |
| `! show this list to the developer` | Show the tree and get an explicit go-ahead **before writing anything**. |
| `-- blind spot:` lines | Relay them. For MongoDB the list is never complete. |

A validator change reaches every document already stored: `errors` and
the apply preview count how many would break it. A unique index meets
every duplicate already stored: the preview looks for them.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "impact shows 0, so nothing uses it" | MongoDB records views only; application code is invisible to it. |
| "It's an optional field, nothing depends on it" | Something wrote it. Search the code. |
| "I'll check impact after writing the command" | Then the number cannot change the design. Too late. |
| "apply's prediction shows what breaks anyway" | It shows views and documents, never the services that read them. |

## Hand-off

Impact known and acceptable → write the change (one command document per
file) → `pythia-mongo-apply` to land it through the gate.
