# Privacy and network behavior

The plugin sends the configured API key, sender, recipient, subject and bodies to MailChannels over HTTPS at api.mailchannels.net. Saving credentials performs dry-run validation with a synthetic message and sender address. Dry-run does not request delivery. Send mode requests delivery to the permitted recipient.

The plugin adds no database, analytics, arbitrary URL retrieval or persistent message storage. Dify supplies provider credentials. The underlying SDK can log method/URL/status; the plugin does not intentionally log secrets or message content. Dify and the host may store configuration, workflow inputs and outputs under their policies. Review access and retention controls before processing personal data.

Output excludes rendered MIME, raw error bodies and headers; it can include request/message identifiers and summarized status. MailChannels processing/retention is governed by the service relationship: consult https://www.mailchannels.com/privacy-policy/ and your agreement. This plugin makes no additional retention guarantee.

Support contact: dev@mailchannels.com.

Credential removal: uninstalling a tool plugin does not necessarily delete its saved Dify credentials. On tested Dify 1.17.1, remove credentials explicitly in provider settings before uninstalling. See README.md for the verified sequence. This removes Dify's stored credential; it does not revoke the upstream MailChannels API key.

Candidate 0.1.1 rejects redirects before forwarding credentials or content to another destination. Successful response bodies have a 2 MiB local cap; other response bodies are discarded.
