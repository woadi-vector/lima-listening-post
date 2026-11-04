# Process my day

The first daily workflow processes a **selected day and project**. It can explicitly include that day's unassigned Bee conversations in that project. It does not silently route a mixed day among different projects, monitor future uploads under a standing cloud permission, or process unfinished audio recordings.

## Prepare, leave, return

1. In Today, choose the day and project. Under What to include, opt into the day's unassigned Bee transcripts if desired and choose the default reading mode for new Bee imports. Existing source reading modes are preserved.
2. Inspect Included sources. Known Bee capture times determine the day in America/Chicago; undated Bee items are held. Imported sources without capture times use import time, labeled visibly. Latest Bee versions are used. Existing imports assigned to another project are not reassigned.
3. Confirm sharing this displayed source snapshot and selected project context with Meta, then click **Process my day**. The snapshot is frozen; later arrivals require a new snapshot and consent.
4. Leave it running and return to **Open daily review**. This needs the Windows computer awake/online and Lima running. It is not a cloud job.

The worker first prepares pending interpretations for all sources. Reference-only sources do not generate outgoing email/calendar proposals. It only proceeds to comparisons/actions after that interpretation phase completes without errors. It then reconciles each source with reviewed project memory, prepares clearly labeled proposed notes, and proposes email/personal-calendar follow-ups. It does not approve work, send mail, create Google drafts, modify calendars, or publish to Notion during preparation.

## Daily review

- Review conversations and work interpretations. New project claims remain pending. Changing reviewed project context can make prepared notes/actions stale; prepare a fresh day snapshot after those changes.
- Inspect the cited comparisons and clarification questions. These remain distinct from confirmed work.
- Open a proposed note, amend it, mark it ready, and separately preview/approve Notion publishing.
- Amend each email proposal and fill missing addresses. Choose Preview Gmail draft or Preview sending email, inspect account/recipients/content, then explicitly approve that exact operation.
- Fill missing calendar times and choose an owned calendar. For an update, choose the exact existing personal event. Inspect overlap warnings and before/after content, then explicitly approve the change.

Saving a Gmail draft and sending from Lima are alternative terminal operations for that local version. A saved Gmail draft is finished in Gmail. No calendar invitations are sent; this release supports personal events only.

## Durability, caching and limits

The day manifest, progress, failures and resulting IDs are persisted. A restart marks active runs interrupted; Resume uses the same consented snapshot. Completed extraction/comparison/action sections are reused where inputs and prompt versions match. A completed unchanged day can be reopened without repeating inference. Cancellation stops after an in-flight section; saved results are retained.

Up to 50 source versions are allowed per snapshot. Missing dates, incomplete sections, invalid quotes, absent recipients, unsupported addresses and uncertain write outcomes are displayed as holds/errors rather than silently filled. The interface reports partial preparation rather than a success claim. Model proposals are limited per section and may miss useful follow-ups; this is not a guarantee that every email or calendar need will be found.

Raw recordings must finish local transcription and be imported first. Bee already supplies transcripts; Lima does not retrieve raw Bee audio. Gmail inbox synchronization, contact-name resolution, shared-calendar awareness and recurring/group-event management are outside this version.

## Verification boundary

Live Meta synthetic day preparation has been exercised, including partial output-limit failure and successful resume. Google account setup, live draft creation and calendar behavior need separate verification after OAuth authorization. Fake-provider tests and UI fixtures are explicitly simulated and perform no real Google writes.

## Process this meeting

Today now offers **Prepare → One meeting now**. Choose one latest Bee transcript or a source linked to the selected project. Lima freezes just that version and uses the same durable interpretation, reconciliation and follow-up preparation worker. Review the displayed source and grant Meta processing consent before starting. The Sources screen also has a **Process this meeting** shortcut.

A meeting can be processed before the end of the day, once Bee has delivered its transcript. Existing per-source caches and versioned outgoing receipts are reused; processing never automatically resends an email or calendar action. Changes to source versions or reviewed project context require fresh preparation and approval. One job runs at a time; a long day can be stopped after its current model section if a meeting needs priority.


## Selected reviews can become reminder drafts

A user can select a non-reference interpretation and explicitly allow Muse to prepare a reminder from that item and its surrounding passage. This creates an unapproved personal-calendar candidate without accepting the interpretation. Original context is attached deterministically so a short phrase such as "do that" retains its preceding subject. Date, time, duration and calendar remain for the user to supply. These candidates are added to the most recent completed day containing that project/source. A lecturer's offer to compile submissions does not become the user's task to compile them. Recurring series are not supported.

The review badge counts an eligible class lesson as one review decision; supporting evidence-point counts remain visible separately. Internal evidence and review history are preserved.


## Simplified daily interface (November 4)

Today shows the day, Process my day, Continue my review and a Saved learning link. Unassigned Bee transcripts for that day are included by default in the displayed, explicitly consented source snapshot. Workspace/scope and inclusion choices remain under Options; project ranking and folder counts are removed from the main daily surface. This is not automatic cross-project routing.

Continue my review opens a short summary followed directly by editable follow-up cards. Calendar drafts use date/time pickers when their existing values have no explicit offset; existing offset-bearing values remain intact. A sole owned calendar is shown as the default selection, still subject to content/destination preview and approval. Save for later retains incomplete drafts locally; it does not create a Google Calendar event. Each send or account write retains its exact approval and duplicate/uncertain-write checks. No batch sending is implied.

Class lessons can be left in Saved learning and opened in a study reader with supporting passages behind a disclosure. Pending class learning remains available without being accepted as project work. Assignment candidates remain in follow-up/evidence review, rather than appearing as an extra class lesson. Projects, subject folders, source import and detailed diagnostics remain reachable through library links and disclosures.

Unfinished, non-dismissed proposals from earlier day jobs are included in the same follow-up queue, with completed deliveries excluded. Stale or uncertain delivery states retain their holds; carrying a draft forward never refreshes its approval or retries a write.
