------------------------------ MODULE Mutants ------------------------------
(* Broken variants of the code. check.mjs swaps each one in with a config  *)
(* override (`Op <- MutantOp`) and requires the named rule to fail. A      *)
(* mutant that passes means the rule can no longer catch that bug.         *)
EXTENDS Publication

\* runner.rs publish_work_order writes project.json Completed before
\* publish_candidate has installed final.ply.
EarlyMeta_Prepare ==
  /\ Live /\ pc = "prepare"
  /\ tx' = [phase |-> "prepared", id |-> cur, out |-> NONE]
  /\ meta' = [status |-> "completed", out |-> cur]
  /\ pc' = "install"
  /\ UNCHANGED <<final, cand, used, dTask, mTask, app, boot, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* publication.rs commit_installed_output runs before the atomic replace of
\* final.ply (steps reordered inside install_and_commit).
CommitFirst_Prepare ==
  /\ Live /\ pc = "prepare"
  /\ tx' = [phase |-> "committed", id |-> cur, out |-> cur]
  /\ pc' = "install"
  /\ UNCHANGED <<final, cand, used, meta, dTask, mTask, app, boot, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>
CommitFirst_Installed ==
  /\ Live /\ pc = "installed"
  /\ pc' = "viewMeta"
  /\ UNCHANGED <<tx, final, cand, used, meta, dTask, mTask, app, boot, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* tasks/mod.rs finish marks the task Completed without looking at the
\* runner's Err.
IgnoreErr_Finish ==
  /\ Live /\ pc = "finish"
  /\ mTask' = IF result # NONE \/ cur # NONE
                THEN [status |-> "completed", result |-> IF result # NONE THEN result ELSE cur]
                ELSE [status |-> "failed", result |-> NONE]
  /\ pc' = "finishPersist"
  /\ UNCHANGED <<tx, final, cand, used, meta, dTask, app, boot, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* tasks/mod.rs load_locked drops reconcile_task_publication: a committed
\* result is only repaired for tasks that were still active.
NoBootReconcile_BootStart ==
  /\ app = "down"
  /\ app' = "booting" /\ mTask' = dTask
  /\ boot' = IF dTask.status = "active" THEN "interrupt" ELSE "persist"
  /\ UNCHANGED <<tx, final, cand, used, meta, dTask, pc, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* tasks/mod.rs load_locked returns reconcile_task_publication's error with
\* `?` (the code before a4b2d97): one final.ply that fails its check, at either
\* of the two checks, leaves `loaded` false and the whole task list unusable.
\* Checked with ExternalEdit.cfg, the only config where final.ply can change.
PropagateErr_BootStart ==
  /\ app = "down"
  /\ mTask' = dTask
  /\ IF tx.phase \in Committedish /\ final # tx.out
       THEN app' = "broken" /\ UNCHANGED boot
       ELSE /\ app' = "booting"
            /\ boot' = IF tx.phase \in Committedish
                         THEN IF tx.phase = "reconciled" /\ dTask.status = "completed"
                                 /\ dTask.result = tx.out
                              THEN "persist" ELSE "pubMeta"
                         ELSE IF dTask.status = "active" THEN "interrupt" ELSE "persist"
  /\ UNCHANGED <<tx, final, cand, used, meta, dTask, pc, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>
PropagateErr_BootPubViews ==
  /\ app = "booting" /\ boot = "pubViews"
  /\ IF final # tx.out
       THEN app' = "broken" /\ UNCHANGED <<tx, mTask, boot>>
       ELSE /\ tx' = IF tx.phase = "committed" THEN [tx EXCEPT !.phase = "views"] ELSE tx
            /\ mTask' = [status |-> "completed", result |-> tx.out]
            /\ boot' = "persist" /\ UNCHANGED app
  /\ UNCHANGED <<final, cand, used, meta, dTask, pc, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>
=============================================================================
