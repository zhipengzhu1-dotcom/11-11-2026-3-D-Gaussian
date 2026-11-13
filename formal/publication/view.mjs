// Reader's words for the /statechart skill's chart and bug paths of Publication.tla.
export const title = "final.ply publication across a crash";

const published = (v) =>
  ({ none: "nothing published", prepared: "publishing", installed: "publishing",
     committed: "result committed", views: "result committed", reconciled: "result committed" })[v.tx.phase];

export const state = (v) => {
  if (v.app === "broken") return "Task list cannot load";
  if (v.app !== "up") return `App restarting (${published(v)})`;
  const task = v.mTask.status === "active" ? "generating" : `task ${v.mTask.status}`;
  return `${task}, ${published(v)}`;
};

export const group = (v) =>
  v.app === "broken" ? "broken" : v.tx.phase === "none" ? "empty" : ["committed", "views", "reconciled"].includes(v.tx.phase) ? "done" : "work";
export const colors = { broken: "pink", empty: "tan", work: "orange", done: "teal" };

const labels = {
  Crash: "the app quits or crashes",
  LoseCandidate: "the Brush candidate file disappears",
  ExternalEdit: "someone deletes or edits final.ply outside the app",
  BootStart: "the app starts and reads its records",
  BootPubMeta: "startup repairs the project record",
  BootPubViews: "startup repairs the project record",
  BootInterrupt: "startup marks the unfinished task",
  BootPersist: "startup saves the task list",
  BootMark: "startup finishes",
  UserStarts: "you start or continue the task",
  Checkpoint: "the task list is saved",
  Reconcile: "the run checks the earlier publication",
  Rebuild: "the run discards an unusable publication",
  MetaRunning: "the run begins",
  Train: "Brush trains a new result",
  Prepare: "publishing begins",
  Install: "final.ply is replaced",
  Installed: "final.ply is verified",
  Commit: "the result is committed",
  ViewMeta: "the project record says completed",
  ViewMark: "the run reports success",
  WriteFails: "a file write fails",
  MetaFailed: "the project record says failed",
  Finish: "the task records the outcome",
  FinishPersist: "the task list is saved",
  FinishMark: "the task list is saved",
  Settled: null,
};
export const step = (action) => labels[action] ?? action;
