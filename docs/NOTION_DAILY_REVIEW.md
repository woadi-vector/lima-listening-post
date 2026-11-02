# Daily review in Notion

Lima creates one dated page per Central calendar day beneath a parent page you select. Each approved draft becomes a collapsible snapshot on that page. Additional notes on the same day reuse that page. The next day gets a new page. There is no automatic publishing schedule.

Create a dedicated Notion integration with Read content and Insert content capabilities. Add that connection to the chosen parent page. In Lima, open Notes → Notion daily review. Paste the parent link and integration secret locally, then connect. Do not paste secrets into a chat. An existing unrelated NOTION_TOKEN environment variable is never used.

Windows protects saved credentials with DPAPI for the current Windows account, in a separate file beside the workspace database. Database backups do not contain this credential file. Protect the containing folder and Windows account. On other platforms, set LIMA_NOTION_TOKEN before launching the app; the local password field does not persist credentials there. An environment LIMA_NOTION_TOKEN takes precedence over a saved Windows credential. Revoke a connection in Notion to remove its access.

Prepare a draft from reviewed project evidence, edit it, save, and approve the local version. Expand Send this note to the daily Notion page → Preview Notion note. Inspect the exact text and destination; tick the confirmation and publish. Previews expire after 30 minutes. Changed drafts, destinations or project evidence require a fresh preview.

Lima appends new snapshots and never overwrites your Notion edits. Delivery receipts and read-back checks prevent ordinary repeated clicks from creating duplicate notes. If a write times out, use Check delivery. Lima does not automatically retry an uncertain write. If the note was edited or deleted remotely, recovery may require manual inspection. It is not a general distributed exactly-once guarantee.

Notes may contain follow-up instructions such as drafting an email. Publishing the note does not send that email or execute its instructions. Model interpretation, local draft approval and Notion publishing are separate steps. Sending email, changing calendars and general Notion synchronization remain outside this connector.

Official API references: https://developers.notion.com/reference/post-page and https://developers.notion.com/reference/patch-block-children. The connector pins API version 2025-09-03, fixes the host to api.notion.com, disables redirects, and does not expose credentials in responses or logs.
