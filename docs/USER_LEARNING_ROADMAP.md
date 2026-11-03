# User learning and assistant roadmap

Confirmed product direction, November 2, 2026.

Lima is a personal assistant that learns the user's preferences and ongoing work over time. Bee supplies captured context; Muse currently supplies interpretation, reconciliation and drafting. A future AWS deployment is an architectural option, not a current integration or a replacement-model decision. Keep capture, model providers, memory and delivery adapters separate so deployment can change without losing reviewed memory or approval controls.

## Verified foundation

Lima stores reviewed evidence-backed project memory, source context and subject folders. Outgoing drafts retain versions and version-specific reviews. This provides history for future adaptation; it does not yet constitute an automatic user preference learner, a trained personal model or voice recognition. Fresh Bee transcript arrival was verified on November 2 for one recording.

## Required personal learning

- Learn correspondence preferences from user-authored corrections and explicitly approved final drafts. Distinguish an approved draft from a confirmed send. Model-generated text alone must not reinforce itself as a user preference.
- Maintain general writing preferences with recipient/relationship and communication-channel overrides: tone, greetings, length, sign-offs and terminology. Spoken conversational style and written correspondence are separate signals.
- Suggest routines, recurring collaborators and preferred project/destination mappings from repeated supported observations. Preserve source dates and uncertainty; distinguish observed patterns from user-confirmed preferences. Never silently create obligations or assume attendance from a routine.
- Treat class lectures, media and other speakers as external context, not evidence of the user's personal beliefs, habits or writing style. Speaker identity requires confirmation; Said versus Focused participation suggestions remain evidence-linked and uncertain where appropriate.
- Provide a visible, editable "What Lima has learned about me" profile. Each preference needs provenance, scope, status, supporting observations and last-confirmed time. Support correction, forgetting, disabling learning and excluding projects or material.
- Keep approved preferences separate from pending suggestions and factual project memory. Personalization cannot invent recipients, dates, commitments or relax approval gates. Forgetting must remove the active preference from future prompt assembly and associated learning records under the defined retention policy.
- Send only relevant approved profile entries to Muse with explicit cloud consent. Do not train a model or export correspondence for training by default.

## Implementation sequence and acceptance

1. Add a versioned preference store and profile editor with evidence links, scoped confirmation and forgetting. Do not migrate historical drafts into confirmed preferences automatically.
2. Capture draft corrections as candidate preference signals; compare original and final versions. Ask for confirmation of durable preferences and allow one-off edits.
3. Include relevant confirmed preferences in drafting prompts. Show which preferences influenced a draft, retain the source evidence and preserve destination-specific approvals.
4. Evaluate held-out drafting examples: user edit effort, preference adherence, factual accuracy and inappropriate cross-recipient transfer. Compare against drafts without the profile; do not claim learning quality from unit tests alone.
5. Add cautious routine and routing suggestions once correspondence learning is observable and correctable. Evaluate Said versus Focused separately before integrating its classifier.

## November 3 field comparison

Process the same day's material with Lima's current attribution/context approach and the original Said versus Focused approach, once its runnable code and requirements have been assessed. Keep separate outputs and compare participation/ambient errors, class/meeting/conversation grouping, uncertainty and false commitment extractions against human review. Do not silently replace production classification or promote comparison results into accepted memory. Capture draft revisions as evaluation examples; automatic personal learning remains unimplemented until the above controls exist.

No scheduled autonomous run is created by this document. Begin the comparison when the user returns with the day's recordings.
