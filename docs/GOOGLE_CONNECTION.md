# Dedicated Lima Google connection

The Google connection inside Codex does not automatically authorize Lima. Lima uses its own Desktop OAuth client and a local loopback callback. The current protected credential setup is exercised on Windows.

## One-time setup

1. Open Google Cloud Console and create/select a dedicated Lima project.
2. Enable **Gmail API** and **Google Calendar API** for that project.
3. Open Google Auth Platform. Configure the app's branding/contact information. For a personal Google account, use **External** audience in **Testing** and add your own Google account as a test user. Workspace policies may require an administrator.
4. Create an OAuth client with application type **Desktop app**, named Lima Desktop. Download its JSON. A web client, API key, or service-account JSON will not work for this flow.
5. In Lima, open **Settings → Google connection** and choose the downloaded JSON file. It is read locally, validated, and protected for your Windows account. Do not paste its contents or tokens into a chat.
6. Click **Sign in with Google**. Complete sign-in and scope review in your regular browser. The local callback returns to Lima. Click **Check connection** to load calendars you own.

Lima requests identity/email, Gmail compose, owned-calendar events, and read-only calendar-list permissions. Gmail compose permits draft management and sending; Lima applies a separate exact-content approval to every outward action. This release does not read or synchronize the Gmail inbox. Google may display a testing/unverified-app notice for your own unpublished OAuth project; verify the client/project and requested scopes yourself.

For an External app in Testing, Google's refresh-token restrictions may require reconnecting; this is a development setup, not a production OAuth verification process. Keep the Desktop JSON and protected credential file private. Revoke access through your Google account when desired.

## Implemented actions

- Prepare editable email text locally, then either create an **unsent Gmail draft** or send that exact approved MIME message. Recipients must be explicit addresses. The app does not guess an address from a name.
- After saving to Gmail drafts, finish/edit/send that draft in Gmail. Lima locks that delivered local version rather than later sending a potentially externally edited draft.
- Propose a timed personal event or update an exact existing personal event on a calendar you own. No attendee invitations, recurring-series edits, shared-calendar writes or automatic date inference are enabled.
- Calendar preview checks overlaps across up to ten owned calendars. It fails rather than claiming a complete check when results are incomplete. Shared calendars are outside that check. Conflicts require explicit acknowledgment; changed conflicts require a fresh preview.
- Existing-event updates show the before/after content and use an ETag precondition. Calendar writes are read back. Gmail sending uses the exact approved raw message and an API acknowledgment, not a claim of recipient delivery.

## Approval and recovery

Previews bind action version, connected account, recipients/destination, exact content, project context and operation, and expire after 15 minutes. Edits invalidate the preview. Each version can produce one terminal delivery; prior related deliveries require inspection before an additional action.

An uncertain network write is marked unconfirmed and is not automatically retried. Check Gmail Sent/Drafts or Calendar manually before any further action. The prototype does not promise distributed exactly-once delivery or automatic recovery for every ambiguous send.

Credentials are DPAPI-protected separately from SQLite backups. OAuth uses PKCE, one-use state and a ten-minute sign-in window. Tokens are refreshed on demand. The app fixes API hosts and disables redirects. None of this makes the local prototype a production multi-user authentication boundary.

Official references:
- https://developers.google.com/identity/protocols/oauth2/native-app
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send
- https://developers.google.com/workspace/calendar/api/v3/reference/events/insert
- https://developers.google.com/workspace/calendar/api/v3/reference/events/patch

Live Gmail/Calendar behavior must be verified after the dedicated account is connected. Simulated provider tests do not establish a working account integration.

## Optional contact capture

Enable People API in the same Lima Google Cloud project. On the Lima computer, use Settings → Google connection → Enable Google Contacts permission and sign in to the same account. This requests the additional `https://www.googleapis.com/auth/contacts` read/write scope, separate from the unchanged default Gmail/Calendar scope set. Lima reads existing personal contacts for a bounded duplicate check and creates only an exact approved new contact. It holds matching names, emails or phone numbers and incomplete scans. It does not automatically merge, update or delete contacts. Live creation/read-back must be verified after authorization. The account's existing Gmail/Calendar connection remains available without opting into contacts.

References: https://developers.google.com/people/api/rest/v1/people/createContact and https://developers.google.com/people/v1/contacts
