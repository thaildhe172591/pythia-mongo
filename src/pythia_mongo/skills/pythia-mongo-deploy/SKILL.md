---
name: pythia-mongo-deploy
description: Use when landing several MongoDB data changes together - a batch of inserts, updates and deletes that must land all or none, or more than one file of them. pythia-mongo deploy rehearses the whole release in one transaction and lands all of it or none of it, under one approval.
---

# Deploy data changes as one transaction

**Announce at start:** "Using pythia-mongo-deploy — the release is rehearsed as one, then approved as one."

**Phase:** Ask → Do — one card for the whole release is the Ask; the confirm is the Do

On a replica set, inserts, updates and deletes can run in one transaction:
if the fifth fails, the first four are not left half-landed. Running them
through mongosh gives that up, and the snapshot and the journal with it.

## The Iron Law

```
A RELEASE LANDS WHOLE, AS APPROVED, OR NOT AT ALL
```

## The Workflow

1. **Impact first** (`pythia-mongo-impact`) for every collection the release
   changes.
2. **The files:** each one command document, or a JSON array of them, in
   the order they must run — one file or several, named in that order on
   the command line. Only data belongs here: `insert`, `update`, `delete`.
3. **Preview:** `pythia-mongo deploy 01_fix.json 02_backfill.json`. Every
   command runs in order inside one transaction, then everything is
   aborted. One card shows every command, the documents each touches, and
   one 10-digit token.
4. **Relay the card verbatim**, then ask through the doors exactly as
   `pythia-mongo-apply` does — AskUserQuestion with the output of
   `pythia-mongo approve --card <token>`, then the `pythia_mongo_approve`
   tool, then `pythia-mongo approve <token>` in the developer's terminal. A
   command's own token is refused: a release is approved as a whole.
5. **Confirm:** the same command with `--confirm <token>` and the same files
   in the same order. It checks every command is byte-identical to what was
   approved, runs the release again in one transaction, and commits only if
   every command still matches — its documents, its count. Otherwise the
   whole release is aborted and the approval stays unspent.
6. **Verify** (`pythia-mongo-verify`).

## What a release cannot hold

A validator, a view, an index, a new or dropped collection: MongoDB runs
them outside any transaction, so they are predicted, not rehearsed, and a
release that lands all or nothing cannot hold them. `deploy` refuses them
before anything is written — apply each on its own, in order, before or
after the data. A commit that does not answer is reported `WRITTEN?` for
the whole release: stop, and show the developer.

## Red Flags — STOP if you catch yourself thinking

| Thought | Reality |
|---------|---------|
| "mongosh with a for loop is how backfills run" | Not here: no rehearsal, no snapshot, no all-or-nothing. The guard denies it. |
| "I'll add the index to the release" | Refused: an index is predicted, not rehearsed. Apply it on its own. |
| "Just one more document after approval" | The files changed: nothing runs. Preview again. |
| "It was aborted, so I'll retry with --yes" | `--yes` is the developer's flag. Find what moved, preview again. |

## When NOT to use this skill

- One command → `pythia-mongo-apply`.
- A standalone server → no transactions: data writes are refused.
