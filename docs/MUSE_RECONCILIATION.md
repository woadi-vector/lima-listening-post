# Muse reconciliation

An explicitly selected source can be compared with up to 20 of its project's most recently reviewed current/conflicted memories. Memory values are limited to 1,200 characters and subjects to 200. The UI explicitly requests consent for sending the source, project name and reviewed context to Meta Muse Spark 1.3. Other projects, unimported Bee inbox items and pending work claims are not sent as reviewed context.

Sources are read in overlapping 16,000-character sections. Legacy Lima report summaries are excluded when a Full Transcript section is present; reports missing it are refused. Each comparison requires an exact distinctive quote. Changes/conflicts also require at least one valid reviewed-memory citation. Questions and follow-ups are model proposals, not confirmed facts or permission to act. Semantic support still needs human review.

Source → Compare with this project → consent → Reconcile with Muse. Results show the source quote, reviewed context, earlier evidence, clarification questions and a proposed next step. Reports also appear under Muse comparisons on the project's Today card. No claims, deadlines or project decisions are automatically changed.

Complete reports with current memory can prepare a local proposed follow-up note. It labels comparisons as proposals and includes evidence from the new source and cited memory. Editing, marking ready and publishing to Notion use the existing version and exact-destination approval flow. Project context changes block note preparation until a new reconciliation is run.

Completed sections are checkpointed by source, project, memory stamp, reading mode and prompt version. A reconnect/restart reuses completed sections; failed sections can be retried with explicit consent. Partial or cancelled reports cannot prepare a note. Old reports remain historical snapshots. A complete report with the same inputs is reused rather than charged for a redundant cloud read.

## Bee automation boundary

Bee delivery polls about once per minute while Lima is running and the computer is awake/online. Optional context suggestions are local. A new upload arrives in the local inbox; Lima does not automatically choose a project or upload every new transcript to Meta.

When importing an individual Bee version, the optional Muse reconciliation checkbox explicitly grants cloud/context consent for that version and selected project. Selecting it queues reconciliation after import instead of the local update-extraction pass. Project or inbox-item changes clear the checkbox. The durable job then runs in the background. It does not grant standing permission for future uploads, import unrelated conversations, confirm work or publish Notion notes.

A truly unattended all-new-upload Muse pipeline would require an explicit standing cloud-sharing scope, an authorized project-routing policy, and recovery/revocation controls. This release does not imply those exist.

## Validation

Tests cover consent before extraction, exact quotes, cross-project isolation, unsupported links, missing prior citations, unchanged project claims, proposed-note evidence, stale context, completed-section reuse, cancellation/resume, legacy report exclusion and background-job dispatch.

A real Muse synthetic Friday-launch scenario produced a conditional comparison and clarification question while retaining the original reviewed decision. The first output cited a shorter passage than the interpretation warranted; the prompt was strengthened to require the quote to support each new-source factual assertion. Both evaluation artifacts are retained. This is a focused smoke check, not a guarantee of semantic correctness or broad accuracy.
