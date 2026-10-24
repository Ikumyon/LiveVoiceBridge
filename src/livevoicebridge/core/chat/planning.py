import html
import re

from livevoicebridge.core.chat.models import CommentEvent, StreamingConfig
from livevoicebridge.core.speech.models import ReadBlockKind, SpeechConfig, SpeechPlan
from livevoicebridge.core.speech.ports import TextProcessor


def plan_comment(
    event: CommentEvent, streaming: StreamingConfig, speech: SpeechConfig, processor: TextProcessor
) -> SpeechPlan | None:
    if (event.history and streaming.skip_history) or (event.paid and not streaming.read_paid_events):
        return None
    message = html.unescape(event.message)
    message = re.sub(r"https?://\S+", "URL", message)
    message = re.sub(r"\s+", " ", message).strip()
    maximum = speech.engine().max_length
    if maximum != -1 and len(message) > maximum:
        message = message[:maximum] + "、以下略"
    values = {ReadBlockKind.AUTHOR: event.author, ReadBlockKind.MESSAGE: message}
    text = "".join(
        block.value if block.kind is ReadBlockKind.TEXT else values[block.kind] for block in speech.read_blocks
    )
    return processor.parse(text)
