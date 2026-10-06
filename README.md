# MailChannels Email API for Dify

A tool plugin for transactional email in workflows and agents. Native Dify installation testing and Marketplace review remain outstanding.

Configure a MailChannels API key, authorized sender, comma-separated exact recipient allowlist (up to 100 addresses), and mode. Default mode validates without sending. Saving credentials always calls `/send?dry-run=true` with a synthetic message from/to the configured sender, even in send mode. This transmits the sender to MailChannels and checks the key and sender without requesting delivery.

Use **Send or validate email** with a recipient, subject, plain-text body and optional HTML. Only provider configuration can change key, sender, recipient permissions and mode. Use separate configurations for separate tenants. Configure Domain Lockdown/DKIM as documented at https://docs.mailchannels.com/email-api/overview. MailChannels requires an account and has separate service charges.

Results: `validated`, `accepted`, `failed`, `rejected` or `unknown`. Accepted is provider handoff, not inbox delivery. No automatic retries are configured. Workflow retry, agent repetition or resumed execution can send twice: this plugin has no durable idempotency. Reconcile unknown outcomes before retrying and enforce application approval/authorization before sending. Attachments, arbitrary headers, custom endpoints and URL downloads are not exposed.

API keys stay in provider credentials. The plugin sends email content only to api.mailchannels.net over HTTPS. It does not return rendered MIME or raw provider errors. Dify may retain workflow inputs/outputs; configure access controls and retention. See PRIVACY.md.

Use Python 3.12; install requirements.txt plus pytest and responses, then run `python -m pytest -q`. Tests intercept HTTP and require no credentials. Package only runtime files with the official Dify CLI. Exclude tests, environments, caches and secrets. Install in an isolated current Dify instance and test workflow/agent behavior before submission. SDK tests are not native installation evidence.

Source: https://github.com/mailchannels/dify-mailchannels

With the official `dify` CLI on PATH, run `python scripts/package.py --output /tmp/mailchannels-0.1.0.difypkg`. The script stages only runtime files. The proposed `mailchannels` publisher namespace and support contact still need company confirmation; no Marketplace submission has occurred.
