---
name: verify-publication-formal
description: Model-check that final.ply publication survives crashes and IO errors. Use when a change touches publication.rs, the publish/reconcile steps in pipeline/runner.rs, TaskService startup or finish in tasks/mod.rs, or project_is_durably_completed in project/catalog.rs, or when a project, task and final.ply can disagree after a crash.
---

# Verify final.ply publication (TLA+)

**The promise:** after any crash or failed write, the app never says a project or task is Completed unless `final.ply` holds that exact result, a committed `final.ply` is never replaced, and the next startup shows a committed result as Completed everywhere. The task list also still loads when a committed `final.ply` was deleted or changed outside the app.

**The harm if it breaks:** a user opens a "Completed" project whose model is missing, belongs to another run, or was lost. Or a finished generation shows as failed or interrupted until something repairs it. Or one damaged project hides every task.

The model is `formal/publication/Publication.tla`. `Publication.cfg` checks every interleaving of one project and one task with up to 2 trained results, 2 crashes, 1 failed runner step and 1 lost candidate file (6,283 states). `ExternalEdit.cfg` adds one edit or deletion of `final.ply` from outside the app, with 1 result and 1 crash (550 states). Two larger bounds also passed at the sync commit: 3 crashes, 2 failed steps and 2 lost candidates (22,535 states), and an outside edit with 2 results, 2 crashes, 1 failed step and 1 lost candidate (28,517 states).

## Run

```sh
node formal/publication/check.mjs          # about 10 s
node formal/publication/check.mjs --trace  # also print TLC's output, with the trace by which each rule catches its mutant
```

It needs Java 11+ and Node 18+. On first run it downloads TLC into a per-user cache and checks its SHA-256. The `v1.8.0` TLC tag is a rolling prerelease, so a fresh download can have another hash. Then set `TLA2TOOLS_JAR` to a known jar, or `OOOSPLAT_TLC_ANY=1` to accept the new build. Exit code 0 means:

1. `PASS protocol holds`: no rule breaks on the model of the current code.
2. `PASS task list loads after final.ply is changed outside the app`: the same holds in `ExternalEdit.cfg`.
3. One `PASS <rule> catches: ...` line per mutant in `formal/publication/Mutants.tla`. Each mutant is a broken variant of the code, and the rule must fail on it. A mutant that passes means the rule went blind. Fix the model, not the mutant.

A `FAIL` line prints TLC's output for that run, and the exit code is 1.

Read every TLC result, pass or fail, with the pstack `/statechart` skill, using `formal/publication/view.mjs` as the view. It gives the shortest path to each broken rule in plain words. It draws the whole state graph only for a run of 500 states or fewer (its documented limit), and both configs are larger. To see how the project moves between states, give it a smaller config: 1 result, 1 crash, 1 failed step and no lost candidate is 415 states. On Windows it fails, from Git Bash too (`spawn /bin/sh ENOENT`), so it needs macOS, Linux or WSL. Without it, read the `--trace` output: every state lists `tx` (transaction phase), `final` (whose bytes are in final.ply), `meta` (project.json), `dTask`/`mTask` (task on disk / in the UI).

## Rules

| Rule | Plain sentence |
| --- | --- |
| `CommittedOutputIntact` | Once the transaction is committed, final.ply holds the committed output. |
| `ProjectCompletedIsReal` | project.json never says Completed unless final.ply holds its output. |
| `TaskCompletedIsReal` | The task, on disk and in the UI, never says Completed unless final.ply holds its result. |
| `StartupConverges` | Right after startup, a committed result shows as Completed in project.json and in the task. |
| `TaskListLoads` | Startup always produces a usable task list, also when a committed final.ply was deleted or changed outside the app. |

`ExternalEdit.cfg` checks only `TaskListLoads`. Once someone outside the app changes final.ply, the other four rules cannot hold, and no other config can break `TaskListLoads`.

## Does my change touch the verified code?

Sync commit: **`a4b2d97d18c00365461152324daf20ff55f365c7`** (the last commit at which the model was confirmed to describe the code).

```sh
git diff a4b2d97d18c00365461152324daf20ff55f365c7 -- src-tauri/src/pipeline/publication.rs src-tauri/src/pipeline/runner.rs src-tauri/src/tasks/mod.rs src-tauri/src/project/catalog.rs src-tauri/src/project/manager.rs src-tauri/src/lib.rs
```

Then check whether the diff touches anything in this coverage record:

| Model action(s) | Code (src-tauri/src/) |
| --- | --- |
| `Prepare`, `Install`, `Installed`, `Commit` | `pipeline/publication.rs`: `publish_candidate`, `install_and_commit`, `commit_installed_output`, `verify_installed_output`, `verify_output_against_candidate` |
| `Reconcile`, `Rebuild` | `pipeline/publication.rs` `reconcile_publication`; `pipeline/runner.rs` `reconcile_publish_transaction` (the `CandidateRebuildRequired` archive), and in `execute_configured_work_order` the `brush_complete` branch that publishes a candidate an earlier run trained, with no Running write and no training |
| `ViewMeta`, `ViewMark` | `pipeline/runner.rs` `publish_work_order` (write_state/write_metadata, then `mark_project_views_reconciled`), and the same tail of `reconcile_publish_transaction` |
| `MetaRunning`, `Train`, `WriteFails`, `MetaFailed` | `pipeline/runner.rs` `execute_configured_work_order` (Running before work, Failed/Cancelled on an Err from the run) |
| `UserStarts`, `Checkpoint` | `tasks/mod.rs` `start_inner`, `spawn_checkpoint_writer` |
| `Finish`, `FinishPersist`, `FinishMark` | `tasks/mod.rs` `finish` (terminal status, `persist`, then `mark_reconciled`) |
| `BootStart` … `BootMark`, `AfterVerifyError` | `tasks/mod.rs` `load_locked` (`AfterVerifyError` is its Err arm), `reconcile_task_publication`; `project/catalog.rs` `project_is_durably_completed`; `lib.rs` setup calling `tasks.initialize()` |
| atomicity of each write | `project/manager.rs` `atomic_write_json`, `atomic_replace_file` |

Each model action is one durable write, or one decision, in that code. The model assumes:

- Each JSON write and the final.ply replace are atomic (temp file + sync + rename).
- File identity is the SHA-256, so two attempts never produce identical bytes.
- Only one generation runs at a time, which TaskService's `gate` and `generation.lock` enforce. The model does not check that.

If the diff touches none of the covered code, you are done: the check still describes the code. If it does, read on.

## Telling a real bug from a modeling error

When a rule breaks, replay the trace against the code, one action per step. Ask whether the real code can take each step in that order: same write, same check, same branch.

- **Every step happens in the code:** it's a real bug. Report it with the steps in the code's words, for example "publish_candidate replaced final.ply, the app crashed before Committed, startup then …". Do not weaken the rule or the model to make it pass, and do not change product code unless the user asks.
- **A step can't happen in the code:** the model is wrong. Common causes: a write the model treats as one step is two in the code, a check the code makes is missing from the model, or a branch condition differs. Fix the model to match the code and rerun.

## When the change is intended

1. Edit the matching action in `Publication.tla` so it again does what the code does, in the same order of durable writes.
2. If a mutant in `Mutants.tla` copies an action you changed, update it too. It must still be the broken version of the new code.
3. Run `node formal/publication/check.mjs`. Every mutant must still be caught.
4. Update the coverage table if functions moved or were renamed.
5. Only after you have read the covered code at the new commit and confirmed the model matches it, set the sync commit above to that commit's full hash. Never move it forward for a change you haven't checked.

## Findings

None open.

**Closed: the task list failed to load if a committed project's final.ply was changed or deleted outside the app** (`TaskListLoads`). `TaskService::load_locked` returned the error of `reconcile_task_publication` through `?`. One project whose final.ply failed its check left `loaded` false, and every later task call failed the same way until the file was restored. Commit `a4b2d97` fixed it: `load_locked` logs the error and changes only that task, and a Completed task becomes Interrupted with `ARTIFACT_UNAVAILABLE`. The old code lives on as the `PropagateErr_*` mutant, which `TaskListLoads` must catch. The fix's own test replays the steps in the real code:

```sh
cargo test --manifest-path src-tauri/Cargo.toml --lib missing_committed_final_ply
```

**Not a rule, but worth knowing:** if a write fails after Commit (`ViewMeta`/`ViewMark`), the run returns Err and the task shows Failed while final.ply is committed. project.json also says Failed if that run had written Running. Otherwise it keeps the Completed that `ViewMeta` wrote. The next continuation or app start repairs both. The model allows this because `StartupConverges` only checks right after startup.

## What this does not cover

- Concurrency between two runs or two processes. The model assumes one runner.
- `reconcile_projects`, `mark_project_deleted`, reshoot snapshots, legacy `output/final.ply` projects (including the `recover_saved_legacy_candidate` branch of `execute_configured_work_order`), and `state.json` contents beyond what the views above imply.
- Cancellation as its own path. It's modeled as a runner Err at the same points.
- Failed writes outside the runner. The failed step always hits the runner. In the code, a failed `persist` in `finish` is only logged: the UI shows Completed while tasks.json still says active, until the next start. A failed project.json write for an interrupted task in `load_locked` still leaves through `?` and fails the whole load.
- What the task and project show after an outside edit, beyond the list loading. The Rust test above covers the task: Interrupted with `ARTIFACT_UNAVAILABLE`, then Completed again once the file is restored and the app restarts.
- Torn writes. Atomic rename is assumed. The fsync of the parent directory is not modeled. Neither is the Windows fallback in `project/manager.rs` `atomic_replace_with_context`, which copies over the destination in place when the rename reports a cross-device error (the code names encrypted folders).
- Any bound above the ones listed at the top.
