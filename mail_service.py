"""Fixed-destination, bounded MailChannels SDK integration."""
from typing import Any

from mailchannels import Client, MailChannelsError, RequestsClient
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr
from requests import RequestException


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr
    sender: EmailStr
    allowed_recipients: str = Field(min_length=1, max_length=30_000)
    mode: str = Field(default="dry_run", pattern="^(dry_run|send)$")

    def allowed(self) -> set[str]:
        from pydantic import TypeAdapter
        addresses = self.allowed_recipients.split(",")
        if len(addresses) > 100:
            raise ValueError("At most 100 allowed recipients")
        adapter = TypeAdapter(EmailStr)
        return {str(adapter.validate_python(a.strip())) for a in addresses}


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: EmailStr
    subject: str = Field(min_length=1, max_length=998, pattern=r"^[^\r\n]+$")
    text: str = Field(min_length=1, max_length=100_000)
    html: str | None = Field(default=None, max_length=100_000)


def settings_from(credentials: dict[str, Any]) -> Settings:
    settings = Settings.model_validate(credentials)
    if not settings.api_key.get_secret_value().strip():
        raise ValueError("Empty API key")
    settings.allowed()
    return settings


def send(settings: Settings, message: Message, *, validation: bool = False) -> dict[str, Any]:
    """Make exactly one SDK request, with no response body or exception leakage."""
    dry_run = validation or settings.mode == "dry_run"
    if not validation and str(message.to) not in settings.allowed():
        return {"status": "rejected", "message": "Recipient is outside configured permissions."}
    content = [{"type": "text/plain", "value": message.text}]
    if message.html:
        content.append({"type": "text/html", "value": message.html})
    payload = {"from": {"email": str(settings.sender)}, "subject": message.subject,
               "personalizations": [{"to": [{"email": str(message.to)}]}], "content": content}
    try:
        with RequestsClient(timeout=30) as transport:
            client = Client(api_key=settings.api_key.get_secret_value(),
                            base_url="https://api.mailchannels.net/tx/v1",
                            http_client=transport, strict_responses=True)
            result = client.emails.send(payload, dry_run=dry_run)
    except (MailChannelsError, RequestException, ValueError):
        return {"status": "unknown", "dry_run": dry_run, "retry_safe": False,
                "message": "Request failed or response is unverified; reconcile before retrying."}
    if dry_run and result.data and not result.results:
        return {"status": "validated", "dry_run": True, "sent": False}
    if not dry_run and result.results and not result.data:
        if len(result.results) == 1 and result.results[0].index == 0:
            item = result.results[0]
            return {"status": "accepted" if item.status == "sent" else "failed",
                    "dry_run": False, "delivery_confirmed": False,
                    "request_id": result.request_id, "message_id": item.message_id}
    return {"status": "unknown", "dry_run": dry_run, "retry_safe": False,
            "message": "Unexpected response variant; reconcile before retrying."}
