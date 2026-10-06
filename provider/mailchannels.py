from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from mail_service import Message, send, settings_from


class MailChannelsProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            settings = settings_from(credentials)
        except (ValueError, TypeError):
            raise ToolProviderCredentialValidationError("Check key, sender, recipient permissions and mode.") from None
        # Saving configuration always validates without sending, even in send mode.
        message = Message(to=settings.sender, subject="MailChannels credential validation",
                          text="Dify plugin credential validation; dry-run only.")
        result = send(settings, message, validation=True)
        if result["status"] != "validated":
            raise ToolProviderCredentialValidationError(
                "MailChannels dry-run validation failed. Check key and sender authorization; no email was requested."
            ) from None
