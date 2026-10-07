# MailChannels Email API for Dify

A tool plugin for transactional email in workflows and agents. Installation, provider credentials and workflow execution have been tested on local Dify 1.17.1 with a synthetic HTTPS MailChannels mock. Browser/model-driven Agent checks, real provider validation and Marketplace review remain outstanding.

Configure a MailChannels API key, authorized sender, comma-separated exact recipient allowlist (up to 100 addresses), and mode. Default mode validates without sending. Saving credentials always calls `/send?dry-run=true` with a synthetic message from/to the configured sender, even in send mode. This transmits the sender to MailChannels and checks the key and sender without requesting delivery.

Use **Send or validate email** with a recipient, subject, plain-text body and optional HTML. Only provider configuration can change key, sender, recipient permissions and mode. Use separate configurations for separate tenants. Configure Domain Lockdown/DKIM as documented at https://docs.mailchannels.com/email-api/overview. MailChannels requires an account and has separate service charges.

Results: `validated`, `accepted`, `failed`, `rejected` or `unknown`. Accepted is provider handoff, not inbox delivery. No automatic retries are configured. Workflow retry, agent repetition or resumed execution can send twice: this plugin has no durable idempotency. Reconcile unknown outcomes before retrying and enforce application approval/authorization before sending. Attachments, arbitrary headers, custom endpoints and URL downloads are not exposed.

API keys stay in provider credentials. The plugin sends email content only to api.mailchannels.net over HTTPS. It does not return rendered MIME or raw provider errors. Dify may retain workflow inputs/outputs; configure access controls and retention. See PRIVACY.md.

Use Python 3.12; install requirements.txt plus pytest and responses, then run `python -m pytest -q`. Tests intercept HTTP and require no credentials. Package only runtime files with the official Dify CLI. Exclude tests, environments, caches and secrets. Install in an isolated current Dify instance and test workflow/agent behavior before submission. SDK tests are not native installation evidence.

Source: https://github.com/mailchannels/dify-mailchannels

With the official `dify` CLI on PATH, run `python scripts/package.py --output /tmp/mailchannels-0.1.1.difypkg`. The script stages only runtime files. Support contact: dev@mailchannels.com. The proposed `mailchannels` Marketplace publisher namespace still needs company registration/ownership; no Marketplace submission has occurred. The manifest declares Dify 1.17.1 as the oldest tested supported version. Older versions have not been validated.

The archive also has serverless-runtime protocol tests. They extract the package into a temporary directory, start its actual entrypoint and provider/tool registration, and call the Dify SDK HTTP runtime. Test-only HTTP interception supplies synthetic MailChannels responses. Run with external networking disabled:

```sh
python scripts/package.py --output /tmp/mailchannels.difypkg
docker build -f tests/Dockerfile -t mailchannels-dify-runtime-test .
docker run --rm --network none -v /tmp/mailchannels.difypkg:/package.difypkg:ro mailchannels-dify-runtime-test
```

These seven protocol scenarios cover credential validation, send/dry-run output, recipient restrictions, injected configuration rejection and uncertain outcomes. They do not test a Dify workspace's editor, daemon upload/installation, encrypted credential storage or Marketplace ownership. Those native acceptance steps remain open.

## Disconnecting

Remove each saved MailChannels credential from Dify's provider settings **before** uninstalling the plugin. On Dify 1.17.1, uninstalling the plugin alone left the tool credential record behind; its `preserve_credentials` option concerns model-provider credentials. Explicitly deleting the tool credential removed its stored record and prevented an existing workflow from making an API request. Uninstalling afterward removed the plugin without leaving tool credential records.

If already uninstalled, the tested recovery is to reinstall the same trusted plugin, delete its saved credentials, then uninstall again. Review workflows referencing that credential: they will fail until deliberately reconfigured. Deleting Dify's saved credential does not revoke the API key at MailChannels. Revoke the dedicated key through MailChannels account management when it is no longer needed; do not revoke a shared key used by other applications.

This lifecycle was tested with synthetic credentials against the native Dify workspace API and checked against the local credential table. It is not a guarantee for every Dify release or a substitute for your account's key-management policy.

Transport boundary in candidate 0.1.1: the plugin supplies its own SDK-compatible Requests transport, restricted to the fixed POST send endpoint with redirects disabled. A response is capped at 2 MiB locally; non-success bodies are discarded. The configured 30-second timeout applies to connection/read inactivity, not a strict wall-clock deadline. Streamed responses and enclosing workflow time limits still require deployment review. The earlier local Dify installation evidence covers 0.1.0; rerun native installation/workflow acceptance for 0.1.1 before Marketplace submission.
