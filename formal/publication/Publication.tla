---------------------------- MODULE Publication ----------------------------
(***************************************************************************)
(* Crash-safe publication of final.ply and the three views that report it. *)
(*                                                                         *)
(* One project, one task, one runner at a time (TaskService allows a       *)
(* single active generation). The app may crash before or after any        *)
(* durable write, and any step of the runner may fail instead (an IO error *)
(* on its write, or the training itself). Writes made by TaskService and   *)
(* by startup never fail here.                                             *)
(*                                                                         *)
(* Code map (src-tauri/src/...):                                           *)
(*   tx       work/publish-transaction.json   pipeline/publication.rs      *)
(*   final    final.ply                       install_and_commit           *)
(*   cand     the Brush candidate per attempt  candidate_relative_path      *)
(*   meta     project.json status + output    ProjectManager::write_metadata*)
(*   dTask    tasks.json (durable task view)   TaskService::persist         *)
(*   mTask    in-memory task view (the UI)     TaskService registry         *)
(*   pc       the runner, PipelineRunner::publish_work_order and            *)
(*            reconcile_publish_transaction (pipeline/runner.rs), then      *)
(*            TaskService::finish (tasks/mod.rs)                            *)
(*   boot     TaskService::load_locked + reconcile_task_publication         *)
(* Each step below is one durable write or one decision in that code.      *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS Attempts,        \* distinct Brush outputs a project can train
          MaxCrashes, MaxErrors, MaxLostCandidates,
          AllowExternalEdit \* TRUE: someone outside the app edits/deletes final.ply once

NONE == "none"
FOREIGN == "foreign"       \* bytes that belong to no publication attempt
Committedish == {"committed", "views", "reconciled"}

VARIABLES tx, final, cand, used, meta, dTask, mTask, app, boot, pc, cur,
          inRun, result, crashes, errors, lost, edits, freshBoot

vars == <<tx, final, cand, used, meta, dTask, mTask, app, boot, pc, cur,
          inRun, result, crashes, errors, lost, edits, freshBoot>>

Out == Attempts \cup {NONE}

TypeOK ==
  /\ tx \in [phase : {"none", "prepared", "installed"} \cup Committedish,
             id : Out, out : Out]
  /\ final \in Out \cup {FOREIGN}
  /\ cand \subseteq Attempts /\ used \subseteq Attempts
  /\ meta \in [status : {"running", "completed", "failed", "interrupted"}, out : Out]
  /\ dTask \in [status : {"created", "active", "completed", "failed", "interrupted"}, result : Out]
  /\ mTask \in [status : {"created", "active", "completed", "failed", "interrupted"}, result : Out]
  /\ app \in {"down", "booting", "up", "broken"}

Init ==
  /\ tx = [phase |-> "none", id |-> NONE, out |-> NONE]
  /\ final = NONE /\ cand = {} /\ used = {}
  /\ meta = [status |-> "running", out |-> NONE]
  /\ dTask = [status |-> "created", result |-> NONE]
  /\ mTask = dTask
  /\ app = "up" /\ boot = "done" /\ pc = "idle" /\ cur = NONE
  /\ inRun = FALSE /\ result = NONE
  /\ crashes = 0 /\ errors = 0 /\ lost = 0 /\ edits = 0
  /\ freshBoot = FALSE

Live == app = "up" /\ boot = "done"

---------------------------------------------------------------------------
(* Environment *)

\* Process dies. Memory (mTask, the runner) is gone; files stay.
Crash ==
  /\ app \in {"up", "booting"} /\ crashes < MaxCrashes
  /\ crashes' = crashes + 1
  /\ app' = "down" /\ boot' = "done" /\ pc' = "idle" /\ cur' = NONE
  /\ inRun' = FALSE /\ result' = NONE /\ freshBoot' = FALSE
  /\ UNCHANGED <<tx, final, cand, used, meta, dTask, mTask, errors, lost, edits>>

\* A candidate checkpoint disappears (artifact cleanup, user, disk).
LoseCandidate ==
  /\ lost < MaxLostCandidates /\ cand # {}
  /\ \E a \in cand : cand' = cand \ {a}
  /\ lost' = lost + 1
  /\ UNCHANGED <<tx, final, used, meta, dTask, mTask, app, boot, pc, cur,
                 inRun, result, crashes, errors, edits, freshBoot>>

ExternalEdit ==
  /\ AllowExternalEdit /\ edits = 0 /\ final \in Attempts
  /\ \E f \in {FOREIGN, NONE} : final' = f
  /\ edits' = 1
  /\ UNCHANGED <<tx, cand, used, meta, dTask, mTask, app, boot, pc, cur,
                 inRun, result, crashes, errors, lost, freshBoot>>

---------------------------------------------------------------------------
(* Startup: TaskService::load_locked (tasks/mod.rs) *)

\* load_locked, the Err arm of reconcile_task_publication: the error is logged
\* and only this task is touched. A Completed task becomes Interrupted with
\* ARTIFACT_UNAVAILABLE and loses its result. An active task takes the normal
\* interrupt path. Any other task stays as it was.
AfterVerifyError ==
  /\ mTask' = IF dTask.status = "completed"
                THEN [status |-> "interrupted", result |-> NONE] ELSE dTask
  /\ boot' = IF dTask.status = "active" THEN "interrupt" ELSE "persist"

BootStart ==
  /\ app = "down"
  /\ app' = "booting"
  /\ IF tx.phase \in Committedish
       THEN \* reconcile_task_publication -> committed_publication verifies final.ply.
            IF final # tx.out THEN AfterVerifyError
            ELSE /\ mTask' = dTask
                 /\ boot' = IF tx.phase = "reconciled" /\ dTask.status = "completed"
                               /\ dTask.result = tx.out
                            THEN "persist" ELSE "pubMeta"
       ELSE /\ mTask' = dTask
            /\ boot' = IF dTask.status = "active" THEN "interrupt" ELSE "persist"
  /\ UNCHANGED <<tx, final, cand, used, meta, dTask, pc, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* reconcile_task_publication: write project.json Completed, then
\* mark_project_views_reconciled, then the in-memory task becomes Completed.
BootPubMeta ==
  /\ app = "booting" /\ boot = "pubMeta"
  /\ meta' = [status |-> "completed", out |-> tx.out]
  /\ boot' = "pubViews"
  /\ UNCHANGED <<tx, final, cand, used, dTask, mTask, app, pc, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* mark_project_views_reconciled verifies final.ply again before it advances
\* the phase. Its error also ends in load_locked's Err arm, with project.json
\* already written Completed.
BootPubViews ==
  /\ app = "booting" /\ boot = "pubViews"
  /\ IF final # tx.out THEN AfterVerifyError /\ UNCHANGED tx
     ELSE /\ tx' = IF tx.phase = "committed" THEN [tx EXCEPT !.phase = "views"] ELSE tx
          /\ mTask' = [status |-> "completed", result |-> tx.out]
          /\ boot' = "persist"
  /\ UNCHANGED <<final, cand, used, meta, dTask, app, pc, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* An active task without a committed publication is Interrupted, unless
\* project_is_durably_completed says otherwise.
BootInterrupt ==
  /\ app = "booting" /\ boot = "interrupt"
  /\ IF tx.phase = "none" /\ meta.status = "completed" /\ final \in Attempts
       THEN \* legacy completion_snapshot path
            /\ mTask' = [status |-> "completed", result |-> meta.out]
            /\ UNCHANGED meta
       ELSE /\ mTask' = [status |-> "interrupted", result |-> dTask.result]
            /\ meta' = [meta EXCEPT !.status = "interrupted"]
  /\ boot' = "persist"
  /\ UNCHANGED <<tx, final, cand, used, dTask, app, pc, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

BootPersist ==
  /\ app = "booting" /\ boot = "persist"
  /\ dTask' = mTask
  /\ boot' = "mark"
  /\ UNCHANGED <<tx, final, cand, used, meta, mTask, app, pc, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* mark_reconciled after the task registry is durable. Its failure only warns.
BootMark ==
  /\ app = "booting" /\ boot = "mark"
  /\ tx' = IF tx.phase \in Committedish /\ final = tx.out /\ dTask.status = "completed"
             THEN [tx EXCEPT !.phase = "reconciled"] ELSE tx
  /\ app' = "up" /\ boot' = "done" /\ freshBoot' = TRUE
  /\ UNCHANGED <<final, cand, used, meta, dTask, mTask, pc, cur, inRun, result,
                 crashes, errors, lost, edits>>

---------------------------------------------------------------------------
(* TaskService::start_inner: the user starts or continues the task. *)

UserStarts ==
  /\ Live /\ pc = "idle"
  /\ mTask.status \in {"created", "failed", "interrupted"}
  /\ mTask' = [mTask EXCEPT !.status = "active"]
  /\ dTask' = [mTask EXCEPT !.status = "active"]
  /\ pc' = "rec" /\ freshBoot' = FALSE /\ inRun' = FALSE
  /\ UNCHANGED <<tx, final, cand, used, meta, app, boot, cur, result,
                 crashes, errors, lost, edits>>

\* spawn_checkpoint_writer persists the registry while a task is active.
Checkpoint ==
  /\ Live /\ mTask.status = "active" /\ dTask # mTask
  /\ dTask' = mTask
  /\ UNCHANGED <<tx, final, cand, used, meta, mTask, app, boot, pc, cur, inRun,
                 result, crashes, errors, lost, edits, freshBoot>>

---------------------------------------------------------------------------
(* The runner *)

Go(next) == pc' = next

Fail ==  \* the runner returns Err
  /\ result' = NONE
  /\ pc' = IF inRun THEN "metaFailed" ELSE "finish"

Keep == UNCHANGED <<final, cand, used, meta, dTask, mTask, app, boot, cur, inRun,
                    crashes, errors, lost, edits, freshBoot>>

\* reconcile_publish_transaction -> publication::reconcile_publication.
\* With no transaction, execute_configured_work_order either starts a normal
\* run, or (brush_complete and a candidate an earlier run trained is still on
\* disk) publishes that candidate at once: no Running write, no training.
Reconcile ==
  /\ Live /\ pc = "rec"
  /\ CASE tx.phase = "none" ->
            \/ Go("metaRunning") /\ UNCHANGED <<cur, result>>
            \/ \E a \in cand : Go("prepare") /\ cur' = a /\ UNCHANGED result
       [] tx.phase = "prepared" ->
            IF tx.id \in cand THEN Go("install") /\ cur' = tx.id /\ UNCHANGED result
            ELSE IF final # NONE
                 THEN IF final = tx.id THEN Go("installed") /\ cur' = tx.id /\ UNCHANGED result
                      ELSE Fail /\ UNCHANGED cur      \* "explicit conflict, never a cache hit"
            ELSE Go("rebuild") /\ UNCHANGED <<cur, result>>
       [] tx.phase = "installed" ->
            IF final = tx.out THEN Go("commit") /\ UNCHANGED <<cur, result>>
            ELSE Fail /\ UNCHANGED cur
       [] tx.phase \in Committedish ->
            IF final = tx.out THEN Go("viewMeta") /\ UNCHANGED <<cur, result>>
            ELSE Fail /\ UNCHANGED cur
  /\ UNCHANGED <<tx, final, cand, used, meta, dTask, mTask, app, boot, inRun,
                 crashes, errors, lost, edits, freshBoot>>

\* CandidateRebuildRequired: archive publish-transaction.json, retrain.
Rebuild ==
  /\ Live /\ pc = "rebuild"
  /\ tx' = [phase |-> "none", id |-> NONE, out |-> NONE]
  /\ pc' = "metaRunning"
  /\ UNCHANGED <<final, cand, used, meta, dTask, mTask, app, boot, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* execute_configured_work_order writes project.json Running, then trains.
MetaRunning ==
  /\ Live /\ pc = "metaRunning"
  /\ meta' = [status |-> "running", out |-> meta.out]
  /\ pc' = "train" /\ inRun' = TRUE
  /\ UNCHANGED <<tx, final, cand, used, dTask, mTask, app, boot, cur, result,
                 crashes, errors, lost, edits, freshBoot>>

Train ==
  /\ Live /\ pc = "train"
  /\ \E a \in Attempts \ used :
       /\ used' = used \cup {a} /\ cand' = cand \cup {a} /\ cur' = a
  /\ pc' = "prepare"
  /\ UNCHANGED <<tx, final, meta, dTask, mTask, app, boot, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* publish_candidate writes a Prepared transaction ...
Prepare ==
  /\ Live /\ pc = "prepare"
  /\ tx' = [phase |-> "prepared", id |-> cur, out |-> NONE]
  /\ pc' = "install"
  /\ UNCHANGED <<final, cand, used, meta, dTask, mTask, app, boot, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* ... install_and_commit hashes the candidate, copies it to a temp file and
\* atomically replaces final.ply ...
Install ==
  /\ Live /\ pc = "install"
  /\ IF cur \in cand
       THEN final' = cur /\ pc' = "installed" /\ UNCHANGED result
       ELSE Fail /\ UNCHANGED final
  /\ UNCHANGED <<tx, cand, used, meta, dTask, mTask, app, boot, cur, inRun,
                 crashes, errors, lost, edits, freshBoot>>

\* ... verifies final.ply against the candidate hash, writes OutputInstalled ...
Installed ==
  /\ Live /\ pc = "installed"
  /\ IF final = cur
       THEN tx' = [phase |-> "installed", id |-> cur, out |-> cur]
            /\ pc' = "commit" /\ UNCHANGED result
       ELSE Fail /\ UNCHANGED tx
  /\ UNCHANGED <<final, cand, used, meta, dTask, mTask, app, boot, cur, inRun,
                 crashes, errors, lost, edits, freshBoot>>

\* ... commit_installed_output re-verifies and writes Committed.
Commit ==
  /\ Live /\ pc = "commit"
  /\ IF final = tx.out
       THEN tx' = [tx EXCEPT !.phase = "committed"] /\ pc' = "viewMeta" /\ UNCHANGED result
       ELSE Fail /\ UNCHANGED tx
  /\ UNCHANGED <<final, cand, used, meta, dTask, mTask, app, boot, cur, inRun,
                 crashes, errors, lost, edits, freshBoot>>

\* write_metadata(Completed, output)
ViewMeta ==
  /\ Live /\ pc = "viewMeta"
  /\ meta' = [status |-> "completed", out |-> tx.out]
  /\ pc' = "viewMark"
  /\ UNCHANGED <<tx, final, cand, used, dTask, mTask, app, boot, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* mark_project_views_reconciled, then the runner returns Ok.
ViewMark ==
  /\ Live /\ pc = "viewMark"
  /\ IF final = tx.out
       THEN /\ tx' = IF tx.phase = "committed" THEN [tx EXCEPT !.phase = "views"] ELSE tx
            /\ result' = tx.out /\ pc' = "finish"
       ELSE Fail /\ UNCHANGED tx
  /\ UNCHANGED <<final, cand, used, meta, dTask, mTask, app, boot, cur, inRun,
                 crashes, errors, lost, edits, freshBoot>>

\* The runner's next step fails instead: an IO error on its durable write, or
\* (at "train") the training itself.
WriteFails ==
  /\ Live /\ errors < MaxErrors
  /\ pc \in {"rebuild", "metaRunning", "train", "prepare", "install", "installed",
             "commit", "viewMeta", "viewMark"}
  /\ errors' = errors + 1
  /\ Fail
  /\ UNCHANGED <<tx, final, cand, used, meta, dTask, mTask, app, boot, cur, inRun,
                 crashes, lost, edits, freshBoot>>

\* On Err after Running was written, the runner writes project.json Failed.
MetaFailed ==
  /\ Live /\ pc = "metaFailed"
  /\ meta' = [meta EXCEPT !.status = "failed"]
  /\ pc' = "finish"
  /\ UNCHANGED <<tx, final, cand, used, dTask, mTask, app, boot, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

\* TaskService::finish: terminal status in memory (an Err clears the result),
\* persist, then mark_reconciled.
Finish ==
  /\ Live /\ pc = "finish"
  /\ mTask' = IF result # NONE THEN [status |-> "completed", result |-> result]
              ELSE [status |-> "failed", result |-> NONE]
  /\ pc' = "finishPersist"
  /\ UNCHANGED <<tx, final, cand, used, meta, dTask, app, boot, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

FinishPersist ==
  /\ Live /\ pc = "finishPersist"
  /\ dTask' = mTask
  /\ pc' = "finishMark"
  /\ UNCHANGED <<tx, final, cand, used, meta, mTask, app, boot, cur, inRun, result,
                 crashes, errors, lost, edits, freshBoot>>

FinishMark ==
  /\ Live /\ pc = "finishMark"
  /\ tx' = IF mTask.status = "completed" /\ tx.phase \in Committedish /\ final = tx.out
             THEN [tx EXCEPT !.phase = "reconciled"] ELSE tx
  /\ pc' = "idle" /\ cur' = NONE /\ inRun' = FALSE /\ result' = NONE
  /\ UNCHANGED <<final, cand, used, meta, dTask, mTask, app, boot,
                 crashes, errors, lost, edits, freshBoot>>

\* Nothing left to do: lets TLC tell a finished history from a deadlock.
Settled ==
  /\ \/ Live /\ pc = "idle" /\ mTask.status = "completed"
     \/ app = "broken"                            \* reached only by a mutant
     \/ Live /\ pc = "train" /\ used = Attempts   \* the bound on retraining is spent
  /\ UNCHANGED vars

Next ==
  \/ Crash \/ LoseCandidate \/ ExternalEdit
  \/ BootStart \/ BootPubMeta \/ BootPubViews \/ BootInterrupt
  \/ BootPersist \/ BootMark
  \/ UserStarts \/ Checkpoint
  \/ Reconcile \/ Rebuild \/ MetaRunning \/ Train \/ Prepare \/ Install
  \/ Installed \/ Commit \/ ViewMeta \/ ViewMark \/ WriteFails \/ MetaFailed
  \/ Finish \/ FinishPersist \/ FinishMark
  \/ Settled

Spec == Init /\ [][Next]_vars

---------------------------------------------------------------------------
(* Rules *)

\* A committed final.ply is never replaced or lost by the app.
CommittedOutputIntact ==
  tx.phase \in Committedish => final = tx.out

\* project.json never says Completed unless final.ply holds that output.
ProjectCompletedIsReal ==
  meta.status = "completed" => (meta.out \in Attempts /\ final = meta.out)

\* The task (durable, and what the UI shows) never says Completed unless
\* final.ply holds that output.
TaskCompletedIsReal ==
  /\ dTask.status = "completed" => (dTask.result \in Attempts /\ final = dTask.result)
  /\ (app = "up" /\ mTask.status = "completed") =>
        (mTask.result \in Attempts /\ final = mTask.result)

\* Right after startup, a committed result is shown as Completed everywhere.
StartupConverges ==
  (Live /\ freshBoot /\ tx.phase \in Committedish) =>
     /\ mTask = [status |-> "completed", result |-> tx.out]
     /\ meta = [status |-> "completed", out |-> tx.out]

\* Startup always produces a usable task list. The code as modelled never
\* sets "broken"; Mutants.tla keeps the variant that does.
TaskListLoads == app # "broken"

=============================================================================
