from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from mail_service import Message, send, settings_from


class SendEmailTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        try:
            settings = settings_from(self.runtime.credentials)
            message = Message.model_validate(tool_parameters)
        except (ValueError, TypeError):
            yield self.create_json_message({"status": "rejected", "message": "Invalid configuration or message fields."})
            return
        yield self.create_json_message(send(settings, message))
