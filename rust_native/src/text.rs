use std::collections::HashMap;

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

#[derive(Default)]
struct TrieNode {
    children: HashMap<char, usize>,
    replacement: Option<String>,
}

#[pyclass]
pub struct DictionaryMatcher {
    nodes: Vec<TrieNode>,
}

#[pymethods]
impl DictionaryMatcher {
    #[new]
    pub fn new(entries: Vec<(String, String)>) -> Self {
        let mut matcher = Self {
            nodes: vec![TrieNode::default()],
        };
        for (word, reading) in entries {
            if word.is_empty() {
                continue;
            }
            let mut node_index = 0usize;
            for character in word.chars() {
                let next = if let Some(index) = matcher.nodes[node_index].children.get(&character) {
                    *index
                } else {
                    let index = matcher.nodes.len();
                    matcher.nodes.push(TrieNode::default());
                    matcher.nodes[node_index].children.insert(character, index);
                    index
                };
                node_index = next;
            }
            matcher.nodes[node_index].replacement = Some(reading);
        }
        matcher
    }

    pub fn replace(&self, text: &str) -> String {
        let characters: Vec<char> = text.chars().collect();
        let mut output = String::with_capacity(text.len());
        let mut start = 0usize;
        while start < characters.len() {
            let mut node_index = 0usize;
            let mut cursor = start;
            let mut longest: Option<(usize, &str)> = None;
            while cursor < characters.len() {
                let Some(next) = self.nodes[node_index].children.get(&characters[cursor]) else {
                    break;
                };
                node_index = *next;
                cursor += 1;
                if let Some(replacement) = self.nodes[node_index].replacement.as_deref() {
                    longest = Some((cursor, replacement));
                }
            }
            if let Some((end, replacement)) = longest {
                output.push_str(replacement);
                start = end;
            } else {
                output.push(characters[start]);
                start += 1;
            }
        }
        output
    }
}

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

fn parse_segments(message: &str) -> (Vec<Segment>, Vec<String>) {
    let mut segments = Vec::new();
    let mut play_files = Vec::new();
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
                play_files.push(path.trim().to_string());
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
    (segments, play_files)
}

fn segment_to_dict<'py>(py: Python<'py>, segment: Segment) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("text", segment.text)?;
    dict.set_item("speed", segment.states.speed)?;
    dict.set_item("pitch", segment.states.pitch)?;
    dict.set_item("volume", segment.states.volume)?;
    dict.set_item("speaker_id", segment.states.speaker_id)?;
    dict.set_item("echo", segment.states.echo)?;
    dict.set_item("yamabiko", segment.states.yamabiko)?;
    dict.set_item("panning", segment.states.panning)?;
    if let Some(action) = segment.action {
        dict.set_item("action", action)?;
    }
    if let Some(word) = segment.word {
        dict.set_item("word", word)?;
    }
    if let Some(reading) = segment.reading {
        dict.set_item("reading", reading)?;
    }
    Ok(dict)
}

#[pyfunction]
pub fn parse_comment<'py>(
    py: Python<'py>,
    message: &str,
) -> PyResult<(Bound<'py, PyList>, Vec<String>)> {
    let (segments, play_files) = parse_segments(message);
    let output = PyList::empty(py);
    for segment in segments {
        output.append(segment_to_dict(py, segment)?)?;
    }
    Ok((output, play_files))
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
    fn dictionary_uses_longest_single_pass_match() {
        let matcher = DictionaryMatcher::new(vec![
            ("東京".to_string(), "とうきょう".to_string()),
            ("東京都".to_string(), "とうきょうと".to_string()),
            ("とうきょうと".to_string(), "再置換しない".to_string()),
        ]);
        assert_eq!(matcher.replace("東京都へ"), "とうきょうとへ");
    }

    #[test]
    fn parser_tracks_state_and_escapes() {
        let (segments, files) = parse_segments("前速度(120)後教育(a\\=b=えー)再生(x\\)y.wav)");
        assert_eq!(segments.len(), 3);
        assert_eq!(segments[0].text, "前");
        assert_eq!(segments[1].text, "後");
        assert_eq!(segments[2].word.as_deref(), Some("a=b"));
        assert_eq!(segments[2].reading.as_deref(), Some("えー"));
        assert_eq!(files, vec!["x)y.wav"]);
    }

    #[test]
    fn sentence_split_matches_full_stop_rule() {
        assert_eq!(split_sentences("一。 二。三"), vec!["一。", "二。", "三"]);
    }
}
