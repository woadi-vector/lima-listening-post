# Private phone access

The Lima computer must remain awake, online and running Mission Control. Your phone must run Tailscale and sign in to the same account. This setup uses private Tailscale Serve, not a public internet link. Check the Tailscale Plans page for your account's plan; the launcher never purchases a plan.

On the Lima computer, double-click **Open Lima on phone.cmd** in the project folder. It checks the existing Tailscale login and starts a separate owner-only loopback gateway on port 8768. It then enables a private HTTPS Serve link. If Tailscale asks you to enable HTTPS, follow its displayed admin link yourself, then run the setup again. Do not enable Funnel. An existing Serve configuration is never overwritten by this launcher.

On the phone, connect Tailscale, open the printed HTTPS link in Safari/Chrome and bookmark it. Open Today, select **Prepare → One meeting now**, choose its project and transcript, review the source snapshot and confirm Meta preparation. The same review and exact approval requirements apply to email, calendar and Notion actions. Google account setup itself stays on the PC.

The gateway accepts only the configured owner's Tailscale identity, supplied by the local Tailscale Serve proxy. It validates the private host and browser origin, then forwards to loopback Mission Control with its existing request token checks. Neither listener binds to the LAN or public interface. Other tailnet users are denied. Local programs on the computer remain trusted, as in the existing local prototype.

Verify access on the phone using mobile data with Tailscale connected. Then disconnect Tailscale: the private page should no longer load (a page already displayed may remain cached onscreen). Reconnect, confirm the project list, and perform a preparation preview. That phone-side check is required before calling this an end-to-end verified connection.

To stop private sharing, run `tailscale serve --https=443 off`. Restart the phone gateway after a computer restart. This prototype does not yet install a Windows background service or automatically change sleep settings.

Official documentation: https://tailscale.com/docs/features/tailscale-serve

## Trial-ended phone sign-in

Tailscale may leave existing PCs connected after a trial ends while preventing a new phone from joining. On the admin console Plans/Billing page, select the Free/Personal plan if the network is for personal, non-commercial use. A custom-domain email can still choose the free plan for personal use. No paid plan is selected by Lima. If only paid plans appear, check the account and contact Tailscale rather than entering payment details for this test. The phone may need reconnecting or approval after the plan change.

The launcher can restart its own gateway while retaining an existing matching Lima Serve configuration. It refuses to replace a different service's configuration.
