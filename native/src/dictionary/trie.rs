//! Immutable radix tree. Updates copy only the modified path.
use std::sync::Arc;

#[derive(Clone, Default)]
pub struct Node {
    reading: Option<Arc<str>>,
    edges: Vec<Edge>,
}

#[derive(Clone)]
struct Edge {
    label: String,
    child: Arc<Node>,
}

fn common_bytes(a: &str, b: &str) -> usize {
    a.chars()
        .zip(b.chars())
        .take_while(|(a, b)| a == b)
        .map(|(c, _)| c.len_utf8())
        .sum()
}

impl Node {
    pub fn update(root: &mut Arc<Self>, word: &str, reading: Option<Arc<str>>) {
        if word.is_empty() {
            Arc::make_mut(root).reading = reading;
            return;
        }
        let first = word.chars().next().expect("nonempty word");
        let node = Arc::make_mut(root);
        match node
            .edges
            .binary_search_by_key(&first, |e| e.label.chars().next().expect("nonempty edge"))
        {
            Err(index) => {
                if reading.is_some() {
                    node.edges.insert(
                        index,
                        Edge {
                            label: word.to_owned(),
                            child: Arc::new(Node {
                                reading,
                                edges: Vec::new(),
                            }),
                        },
                    );
                }
            }
            Ok(index) => {
                let edge = &mut node.edges[index];
                let common = common_bytes(word, &edge.label);
                if common < edge.label.len() {
                    if reading.is_none() {
                        return;
                    }
                    let suffix = edge.label[common..].to_owned();
                    let previous = Arc::clone(&edge.child);
                    edge.label.truncate(common);
                    edge.child = Arc::new(Node {
                        reading: None,
                        edges: vec![Edge {
                            label: suffix,
                            child: previous,
                        }],
                    });
                }
                Self::update(&mut edge.child, &word[common..], reading);
                if edge.child.reading.is_none() {
                    if edge.child.edges.is_empty() {
                        node.edges.remove(index);
                    } else if edge.child.edges.len() == 1 {
                        let child = &edge.child.edges[0];
                        edge.label.push_str(&child.label);
                        edge.child = Arc::clone(&child.child);
                    }
                }
            }
        }
    }

    pub fn replace(&self, text: &str) -> String {
        let mut output = String::with_capacity(text.len());
        let mut start = 0;
        while start < text.len() {
            let mut node = self;
            let mut cursor = start;
            let mut longest = None;
            while cursor < text.len() {
                let remaining = &text[cursor..];
                let first = remaining.chars().next().expect("nonempty text");
                let Ok(index) = node.edges.binary_search_by_key(&first, |e| {
                    e.label.chars().next().expect("nonempty edge")
                }) else {
                    break;
                };
                let edge = &node.edges[index];
                if !remaining.starts_with(&edge.label) {
                    break;
                }
                cursor += edge.label.len();
                node = &edge.child;
                if let Some(reading) = &node.reading {
                    longest = Some((cursor, reading.as_ref()));
                }
            }
            if let Some((end, reading)) = longest {
                output.push_str(reading);
                start = end;
            } else {
                let character = text[start..].chars().next().expect("nonempty text");
                output.push(character);
                start += character.len_utf8();
            }
        }
        output
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn longest_match_is_single_pass_and_snapshots_are_immutable() {
        let mut root = Arc::new(Node::default());
        for (word, reading) in [
            ("東京", "とうきょう"),
            ("東京都", "とうきょうと"),
            ("とうきょうと", "再置換しない"),
        ] {
            Node::update(&mut root, word, Some(Arc::from(reading)));
        }
        assert_eq!(root.replace("東京都へ"), "とうきょうとへ");
        let previous = Arc::clone(&root);
        Node::update(&mut root, "東京都", None);
        assert_eq!(root.replace("東京都へ"), "とうきょう都へ");
        assert_eq!(previous.replace("東京都へ"), "とうきょうとへ");
        Node::update(&mut root, "東京", None);
        assert_eq!(root.replace("東京都へ"), "東京都へ");
    }

    #[test]
    fn radix_splits_unicode_edges_and_replaces_existing_readings() {
        let mut root = Arc::new(Node::default());
        for (word, reading) in [
            ("あいう", "A"),
            ("あえ", "B"),
            ("あ", "C"),
            ("あいう", "D"),
            ("😀あ", "E"),
        ] {
            Node::update(&mut root, word, Some(Arc::from(reading)));
        }
        assert_eq!(root.replace("あいうあえあお😀あ"), "DBCおE");
        Node::update(&mut root, "存在しない", None);
        assert_eq!(root.replace("あいう"), "D");
    }
}
