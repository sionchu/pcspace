# Security and data safety

PCSpace runs with your Windows account's filesystem permissions. It is a local utility, not a security sandbox, backup system, or multi-user file server. **Do not expose its backend to the public internet.**

The supported deployment binds to `127.0.0.1`, disables proxy-header interpretation, validates Host/Origin and CSRF, and creates an automatic session for the local browser. Optional remote access trusts identity headers inserted by **Tailscale Serve** from allowlisted users. Other reverse proxies are not supported. Do not forward arbitrary public headers into this endpoint or use Tailscale Funnel. Tagged Tailscale devices may not provide a user identity.

No extra local password is requested. Any program already running as the local OS user can act with that user's privileges. Root, system, credential-store, cloud/reparse-point, and explicitly protected-path checks reduce accidents; they do not protect against an adversarial local user racing path changes.

Permanent deletion cannot be undone. The preview is not a backup. Files created or modified after a preview can cause an operation to be refused or partially fail. Native recycle never silently falls back to permanent deletion. Recycle Bin contents still occupy drive space.

The app performs metadata scans, not a file-content upload. It does not run an AI model, send analytics, or automatically clean files. Scan data and action history live under `%LOCALAPPDATA%\PCSpace` and can contain private paths. Keep that folder out of public reports.

The Pages demo is static and uses fictional sample data. It has no backend and cannot scan or delete files.

To report a security issue, use GitHub's private vulnerability reporting for this repository when enabled. Otherwise open a minimal issue requesting a private reporting channel **without publishing exploit details or personal data**. No response-time SLA is offered for this early project.
