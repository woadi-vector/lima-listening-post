# Lima Listening Post

Bee captures the conversation. Muse prepares the follow-through. You review it. Notion holds the daily record.

Lima connects what was said to ongoing work using exact source evidence, project memory and an editable review queue. It can prepare a full day in the background or one meeting when a follow-up cannot wait.

## Personal assistant direction

Lima is intended to learn the user’s correspondence preferences, routines and project context through reviewed evidence and corrections. Today it retains project memory and draft versions; automatic personal preference learning is planned, not implemented. Bee and Muse are the current workflow. AWS deployment is a future option. See the [user learning roadmap](docs/USER_LEARNING_ROADMAP.md).

## Try the repeatable demo

Requires Python 3.11 or newer. Development and controlled account checks use Windows/Python 3.13.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m lima_next.demo --showcase --db demo-data/showcase.sqlite3
python -m lima_next serve --db demo-data/showcase.sqlite3 --port 8766
```

Open http://127.0.0.1:8766 and choose **Open daily review**. This is an offline replay of real Muse Spark 1.3 outputs on a scripted synthetic meeting. The earlier reviewed decision is a fixture. No account is connected, no fresh model call is claimed and no outward action runs. Existing demo files are never reset; use a new database name to repeat.

For a fresh model run, create a source-only workspace with `python -m lima_next.demo --day-workflow --db demo-data/fresh.sqlite3`, set MODEL_API_KEY in the process environment, serve that database and explicitly start processing in the UI. See [the three-minute runbook](docs/DEMO_RUNBOOK.md).

On macOS/Linux, activate the environment with `source .venv/bin/activate`. Windows is the exercised desktop platform. Portable core tests and mocked integrations do not establish end-to-end desktop parity.

## The workflow

1. Bee's completed transcripts arrive in Lima's durable local inbox. Local audio can also be transcribed and reviewed before import.
2. Process a selected day or meeting with explicit Meta consent. Muse organizes and interprets the material, reconciles reviewed project context and drafts supported follow-ups.
3. Review context groups and subject folders. Class notes, tentative ideas, decisions and commitments stay distinct. Source capture dates and human review dates are shown separately.
4. Amend and approve exact destinations and content for email, personal calendar and Notion actions. Texts are copyable drafts only. Contact creation requires optional People API authorization.
5. Refresh and approve the Muse-written daily Notion repository note after actions change. Notion is a one-way reviewed snapshot; it does not execute instructions in a note or synchronize edits back into Lima.

**Nothing is sent, posted or confirmed without approval.** An uncertain write is held for inspection rather than automatically repeated.

## Run your own workspace

```powershell
python -m lima_next serve --open-browser
```

The service binds to loopback, normally http://127.0.0.1:8765. Keep its computer awake and running. Optional private phone access uses the owner-restricted Tailscale gateway; see [phone setup](docs/PHONE_ACCESS.md).

Connections are per workspace:

- **Muse Spark 1.3:** provide MODEL_API_KEY locally. Day/meeting processing sends the selected snapshot and permitted project context to Meta. Automatic future Bee uploads are not automatically sent to Meta.
- **Bee:** install/sign in to the official CLI, then enable delivery. The connector imports transcripts; it does not assume raw audio or Bee summaries are available. A confirmed missing queued conversation is recorded and skipped without deleting saved sources.
- **Ollama:** optional local context/interpretation through llama3.1:8b. Automatic Bee context suggestions stay local.
- **Google:** dedicated Desktop OAuth with Gmail compose and owned personal-calendar access. [Setup](docs/GOOGLE_CONNECTION.md). Contacts is an explicit additional read/write permission.
- **Notion:** use a dedicated Lima integration and review parent. [Setup](docs/NOTION_DAILY_REVIEW.md). A dated page is created on the first approved publish each day; later approved notes append.

Never commit tokens, downloaded OAuth JSON, workspace databases or recordings. Protected local account credentials are stored separately from database backups. The current credential setup uses Windows DPAPI.

## Validation and limits

Controlled live checks cover Gmail unsent draft/send acknowledgment, personal calendar create/update read-back and Notion publication/read-back. A live Muse synthetic run produced email, text, contact and calendar proposals plus a daily repository draft; its initial output-limit failure and successful resumed run were retained. Tests are software checks and small synthetic evaluations, not a broad accuracy score.

Direct SMS sending, automatic speaker identity, Zoom/Teams connectors, two-way Notion synchronization and automatic cross-project routing are not implemented. Google Contacts creation is implemented but its controlled live write remains deferred. Existing subject names are matched within a project; semantic matches remain model proposals, not proven classification.

See [validation](VALIDATION.md), [Muse outputs](docs/MUSE_OUTPUTS.md), [subject folders](docs/SUBJECT_FOLDERS.md) and [security notes](SECURITY.md).

## Tests

```powershell
python -m pip install -e . numpy av
python -B -m unittest discover -s tests_next -q
```

NumPy/PyAV exercise optional audio tests without downloading model weights. Actual transcription additionally requires the `audio` optional dependencies. Tests without those optional libraries disclose skips.

## Development and license

This is the rebuilt `lima_next` core, developed with AI coding assistance from an earlier Windows/Python product vision. Legacy code, private handoffs, recordings, data and credentials are excluded. The initial clean repository commit reflects this import; it does not reconstruct historical development commits. See [contributions](CONTRIBUTIONS.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

The rebuilt core is licensed under [MIT](LICENSE), copyright 2026 Jason Wold. Third-party dependencies, model weights and services retain their own terms.
