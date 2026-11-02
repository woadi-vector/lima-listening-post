# Prototype data and security boundaries

- Local single-user app, bound to loopback. Token/Origin/Host checks protect browser actions; this is not a tenant isolation or remote deployment boundary.
- SQLite and ordinary transcript files are not encrypted by the app. Protect the Windows account, disk and backups.
- Windows Notion secrets and Google Desktop OAuth credentials are separately DPAPI-protected. Other platforms use an environment credential. MODEL_API_KEY is process environment only. Never commit keys, DPAPI files, recordings or databases.
- Cloud source reading requires explicit consent. Notion delivery requires an approved local version plus exact-content/destination preview and confirmation. Google email execution and personal-calendar writes require a separate exact account/content/destination preview and approval. No arbitrary host, redirect or unattended publishing path is provided.
- Notion receipts and read-back checks reduce duplicates. An uncertain network outcome requires inspection; there is no universal exactly-once guarantee. Edits made in Notion are not overwritten or synchronized back into Lima.
- Quoted source text is treated as untrusted data. Exact quote matching and attribution checks are safeguards, not proof of semantic correctness. Do not infer agreement or ownership from first-person language alone.
- Retention/forgetting controls, derived-data deletion, multi-device authentication, encryption-at-rest, generalized connection revocation management and production recovery need further work.

This candidate's allowlist excludes private runtime assets. The automated release scan checks known environment credentials and obvious patterns, but is not a complete audit. Review the manifest and intended contents before any public push.
