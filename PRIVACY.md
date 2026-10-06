# Privacy and network behavior

The plugin sends the configured API key, sender, recipient, subject and bodies to MailChannels over HTTPS at api.mailchannels.net. Saving credentials performs dry-run validation with a synthetic message and sender address. Dry-run does not request delivery. Send mode requests delivery to the permitted recipient.

The plugin adds no database, analytics, arbitrary URL retrieval or persistent message storage. Dify supplies provider credentials. The underlying SDK can log method/URL/status; the plugin does not intentionally log secrets or message content. Dify and the host may store configuration, workflow inputs and outputs under their policies. Review access and retention controls before processing personal data.

Output excludes rendered MIME, raw error bodies and headers; it can include request/message identifiers and summarized status. MailChannels processing/retention is governed by the service relationship: consult https://www.mailchannels.com/privacy-policy/ and your agreement. This plugin makes no additional retention guarantee.

A monitored publisher support contact must be confirmed before submission.
