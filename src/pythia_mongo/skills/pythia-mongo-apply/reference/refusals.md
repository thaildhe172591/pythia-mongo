# Refusals and the way forward

`pythia-mongo apply` refuses what it cannot rehearse, predict or undo
honestly. Each refusal exits 1 and writes nothing. Relay the reason, then
offer the way forward below — never run the command another way.

| Refused | Why | Way forward |
|---|---|---|
| mongosh JavaScript (`db.t.insertOne(...)`) | pythia-mongo runs command documents, not a shell | the command document: `{"insert": "t", "documents": [...]}` |
| several commands in one file, or an array | each is previewed, approved and journaled on its own | one file per command — or `pythia-mongo deploy` for data |
| an update or a delete holding several statements | each is previewed on its own | one statement per file — or `pythia-mongo deploy` |
| a `collMod` changing a view, a validator and an option together | each is previewed and restored on its own | one change per file |
| a key written twice | which one MongoDB would use is a guess | write it once |
| `$where`, `$function`, `$accumulator`, code, `mapReduce` | JavaScript runs inside the server and can do anything | query operators and aggregation expressions |
| `$out`, `$merge` | a pipeline that writes; a prediction runs pipelines before approval | not through apply: the developer decides |
| `aggregate`, `find` | apply takes writes | reads go through `ls`, `src`, `cols`, `grep` |
| `findAndModify` | changes one document and returns it | an `update` or a `delete` |
| an upsert | its documents cannot be shown beforehand | an `insert`, or an `update` |
| an update without `"multi": true`, a delete with `"limit": 1` | one document among all its filter matches — which one, nobody can see | `"multi": true` / `"limit": 0`, or name the document by `_id` |
| users and roles | a `createUser` carries a password into the file and the journal | a DBA, by hand |
| `renameCollection`, `dropDatabase` | breaks every view and application that names it | a DBA, by hand |
| `bypassDocumentValidation` | skips the validator | fix the documents, or change the validator through apply |
| `lsid`, `txnNumber`, `writeConcern`, `readConcern` | pythia-mongo owns the session and the transaction | leave them out |
| a `system.` collection | MongoDB's own | not through apply |
| data on a standalone server | rehearsals need a transaction, transactions a replica set | a single-node replica set, for development |
| a prediction MongoDB would refuse (a bad validator, an unknown stage), or a unique index with duplicates | there is nothing to approve | fix the command, or the duplicates first |
| a group set to `deny` | the policy | relay it; loosening is the developer's `policy set`, at a console |

When the gate refuses, the developer may still decide to run the command
by hand. Hand them the file and, for a view or a validator, the restore
from `pythia-mongo history <name>` — never run it for them through mongosh.
