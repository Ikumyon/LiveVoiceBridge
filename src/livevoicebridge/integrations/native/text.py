import emoji

from livevoicebridge import _native as native
from livevoicebridge.core.dictionary.models import DictionarySnapshot
from livevoicebridge.core.speech.models import (
    DictionaryCommand,
    SoundEffect,
    SpeechAction,
    SpeechControls,
    SpeechItem,
    SpeechPlan,
    Utterance,
)


class NativeTextProcessor:
    def parse(self, text: str) -> SpeechPlan:
        items: list[SpeechItem] = []
        for segment in native.parse_comment(text):
            if segment.action == "sound":
                items.append(SoundEffect(str(segment.word)))
                continue
            controls = SpeechControls(
                speaker_id=segment.speaker_id,
                speed=segment.speed,
                pitch=segment.pitch,
                volume=segment.volume,
                echo=segment.echo,
                yamabiko=segment.yamabiko,
                panning=segment.panning,
            )
            for sentence in native.split_sentences(str(segment.text)):
                if sentence.strip():
                    items.append(Utterance(sentence, controls))
            action = segment.action
            if action:
                items.append(DictionaryCommand(SpeechAction(action), str(segment.word), str(segment.reading or "")))
        return SpeechPlan(tuple(items))

    def prepare(self, text: str, dictionary: DictionarySnapshot) -> str:
        text = dictionary.replace(text)
        for item in reversed(emoji.emoji_list(text)):
            replacement = emoji.demojize(item["emoji"], language="ja").strip(":")
            text = text[: item["match_start"]] + replacement + text[item["match_end"] :]
        return text
