use pyo3::prelude::*;

#[derive(Clone, Default)]
struct States {
    speed: Option<f64>,
    pitch: Option<f64>,
    volume: Option<f64>,
    speaker_id: Option<i64>,
    echo: Option<i64>,
    yamabiko: Option<i64>,
    panning: Option<String>,
}

struct Segment {
    text: String,
    states: States,
    action: Option<&'static str>,
    word: Option<String>,
    reading: Option<String>,
}

fn escaped_content(text: &str, open_paren: usize) -> Option<(String, usize)> {
    let mut output = String::new();
    let mut escaped = false;
    for (relative, character) in text[open_paren + 1..].char_indices() {
        let position = open_paren + 1 + relative;
        if escaped {
            output.push(character);
            escaped = false;
        } else if character == '\\' {
            escaped = true;
        } else if character == ')' {
            return Some((output, position + character.len_utf8()));
        } else {
            output.push(character);
        }
    }
    None
}

fn escaped_pair(text: &str, open_paren: usize) -> Option<(String, String, usize)> {
    let mut output = String::new();
    let mut escaped = false;
    let mut equals = None;
    for (relative, character) in text[open_paren + 1..].char_indices() {
        let position = open_paren + 1 + relative;
        if escaped {
            output.push(character);
            escaped = false;
        } else if character == '\\' {
            escaped = true;
        } else if character == '=' && equals.is_none() {
            equals = Some(output.len());
        } else if character == ')' {
            let split = equals?;
            let word = output[..split].trim().to_string();
            let reading = output[split..].trim().to_string();
            return Some((word, reading, position + character.len_utf8()));
        } else {
            output.push(character);
        }
    }
    None
}

fn numeric_command(remaining: &str, command: &str) -> Option<(i64, usize)> {
    let prefix = format!("{command}(");
    let rest = remaining.strip_prefix(&prefix)?;
    let close = rest.find(')')?;
    let digits = &rest[..close];
    if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    Some((digits.parse().ok()?, prefix.len() + close + 1))
}

fn flush_text(segments: &mut Vec<Segment>, text: &mut String, states: &States) {
    let clean = text.trim();
    if !clean.is_empty() {
        segments.push(Segment {
            text: clean.to_string(),
            states: states.clone(),
            action: None,
            word: None,
            reading: None,
        });
    }
    text.clear();
}

fn parse_segments(message: &str) -> Vec<Segment> {
    let mut segments = Vec::new();
    let mut states = States::default();
    let mut accumulated = String::new();
    let mut index = 0usize;

    while index < message.len() {
        let remaining = &message[index..];

        if remaining.starts_with("教育") {
            if let Some(relative_open) = remaining.find('(') {
                let open = index + relative_open;
                if let Some((word, reading, end)) = escaped_pair(message, open) {
                    flush_text(&mut segments, &mut accumulated, &states);
                    segments.push(Segment {
                        text: format!("{word}が{reading}に辞書登録されました。"),
                        states: states.clone(),
                        action: Some("add_dict"),
                        word: Some(word),
                        reading: Some(reading),
                    });
                    index = end;
                    continue;
                }
            }
        }

        if remaining.starts_with("忘却") {
            if let Some(relative_open) = remaining.find('(') {
                let open = index + relative_open;
                if let Some((word, end)) = escaped_content(message, open) {
                    let word = word.trim().to_string();
                    flush_text(&mut segments, &mut accumulated, &states);
                    segments.push(Segment {
                        text: format!("{word}が辞書から削除されました。"),
                        states: states.clone(),
                        action: Some("del_dict"),
                        word: Some(word),
                        reading: None,
                    });
                    index = end;
                    continue;
                }
            }
        }

        let play_prefix = ["再生(", "音(", "sound("]
            .iter()
            .find(|prefix| remaining.starts_with(**prefix));
        if let Some(prefix) = play_prefix {
            let open = index + prefix.len() - 1;
            if let Some((path, end)) = escaped_content(message, open) {
                flush_text(&mut segments, &mut accumulated, &states);
                segments.push(Segment {
                    text: String::new(),
                    states: states.clone(),
                    action: Some("sound"),
                    word: Some(path.trim().to_string()),
                    reading: None,
                });
                index = end;
                continue;
            }
        }

        let mut matched = None;
        for command in ["速度", "音程", "音量", "声", "エコー", "やまびこ"] {
            if let Some((value, consumed)) = numeric_command(remaining, command) {
                matched = Some((command, value, consumed));
                break;
            }
        }
        if let Some((command, value, consumed)) = matched {
            flush_text(&mut segments, &mut accumulated, &states);
            match command {
                "速度" => states.speed = Some(value as f64 / 100.0),
                "音程" => states.pitch = Some((value as f64 - 100.0) / 100.0 * 0.15),
                "音量" => states.volume = Some(value as f64 / 100.0),
                "声" => states.speaker_id = Some(value),
                "エコー" => states.echo = Some(value),
                "やまびこ" => states.yamabiko = Some(value),
                _ => unreachable!(),
            }
            index += consumed;
            continue;
        }

        let pan = [
            ("左)", "left"),
            ("右)", "right"),
            ("両)", "both"),
            ("左）", "left"),
            ("右）", "right"),
            ("両）", "both"),
        ]
        .iter()
        .find(|(prefix, _)| remaining.starts_with(prefix));
        if let Some((prefix, direction)) = pan {
            flush_text(&mut segments, &mut accumulated, &states);
            states.panning = Some((*direction).to_string());
            index += prefix.len();
            continue;
        }

        let character = remaining.chars().next().expect("valid UTF-8 character");
        accumulated.push(character);
        index += character.len_utf8();
    }
    flush_text(&mut segments, &mut accumulated, &states);
    segments
}

#[pyclass(frozen, get_all)]
pub struct ParsedSegment {
    pub text: String,
    pub speed: Option<f64>,
    pub pitch: Option<f64>,
    pub volume: Option<f64>,
    pub speaker_id: Option<i64>,
    pub echo: Option<i64>,
    pub yamabiko: Option<i64>,
    pub panning: Option<String>,
    pub action: Option<String>,
    pub word: Option<String>,
    pub reading: Option<String>,
}

#[pyfunction]
pub fn parse_comment(py: Python<'_>, message: &str) -> Vec<ParsedSegment> {
    py.detach(|| {
        parse_segments(message)
            .into_iter()
            .map(|segment| ParsedSegment {
                text: segment.text,
                speed: segment.states.speed,
                pitch: segment.states.pitch,
                volume: segment.states.volume,
                speaker_id: segment.states.speaker_id,
                echo: segment.states.echo,
                yamabiko: segment.states.yamabiko,
                panning: segment.states.panning,
                action: segment.action.map(str::to_owned),
                word: segment.word,
                reading: segment.reading,
            })
            .collect()
    })
}

#[pyfunction]
pub fn split_sentences(text: &str) -> Vec<String> {
    let mut output = Vec::new();
    let mut current = String::new();
    for character in text.chars() {
        current.push(character);
        if character == '。' {
            let sentence = current.trim();
            if !sentence.is_empty() {
                output.push(sentence.to_string());
            }
            current.clear();
        }
    }
    let sentence = current.trim();
    if !sentence.is_empty() {
        output.push(sentence.to_string());
    }
    output
}

#[pyfunction]
pub fn hiragana_to_katakana(text: &str) -> String {
    text.chars()
        .map(|character| {
            if ('\u{3041}'..='\u{3096}').contains(&character) {
                char::from_u32(character as u32 + 0x60).unwrap_or(character)
            } else {
                character
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parser_tracks_state_and_escapes() {
        let segments = parse_segments("前速度(120)後教育(a\\=b=えー)再生(x\\)y.wav)");
        assert_eq!(segments.len(), 4);
        assert_eq!(segments[0].text, "前");
        assert_eq!(segments[1].text, "後");
        assert_eq!(segments[2].word.as_deref(), Some("a=b"));
        assert_eq!(segments[2].reading.as_deref(), Some("えー"));
        assert_eq!(segments.last().unwrap().word.as_deref(), Some("x)y.wav"));
    }

    #[test]
    fn sentence_split_matches_full_stop_rule() {
        assert_eq!(split_sentences("一。 二。三"), vec!["一。", "二。", "三"]);
    }
}
