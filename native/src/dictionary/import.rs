//! Streaming imports: at most one source row is deserialized at a time.
use std::fmt;
use std::fs::File;
use std::io::{BufRead, BufReader, Read, Seek};
use std::path::Path;

use encoding_rs::{SHIFT_JIS, UTF_16BE, UTF_16LE, UTF_8};
use encoding_rs_io::DecodeReaderBytesBuilder;
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer};

#[derive(Default, Deserialize)]
#[serde(default)]
pub struct Row {
    pub word: String,
    pub reading: String,
    #[serde(rename = "pos", alias = "part_of_speech")]
    pub pos: String,
    pub comment: String,
}

type Sink<'a> = dyn FnMut(Option<&str>, Row) -> Result<(), String> + 'a;

struct ImportSeed<'a, 'b> {
    sink: &'a mut Sink<'b>,
    group: Option<String>,
}

impl<'de> DeserializeSeed<'de> for ImportSeed<'_, '_> {
    type Value = ();

    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<(), D::Error> {
        deserializer.deserialize_any(self)
    }
}

impl<'de> Visitor<'de> for ImportSeed<'_, '_> {
    type Value = ();

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a dictionary array or object")
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<(), A::Error> {
        while let Some(row) = seq.next_element::<Row>()? {
            (self.sink)(self.group.as_deref(), row).map_err(de::Error::custom)?;
        }
        Ok(())
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<(), A::Error> {
        while let Some(key) = map.next_key::<String>()? {
            map.next_value_seed(ValueSeed {
                sink: self.sink,
                key,
            })?;
        }
        Ok(())
    }
}

struct ValueSeed<'a, 'b> {
    sink: &'a mut Sink<'b>,
    key: String,
}

impl<'de> DeserializeSeed<'de> for ValueSeed<'_, '_> {
    type Value = ();

    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<(), D::Error> {
        deserializer.deserialize_any(self)
    }
}

impl<'de> Visitor<'de> for ValueSeed<'_, '_> {
    type Value = ();

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a reading string or group array")
    }

    fn visit_str<E: de::Error>(self, value: &str) -> Result<(), E> {
        (self.sink)(
            None,
            Row {
                word: self.key,
                reading: value.into(),
                ..Row::default()
            },
        )
        .map_err(E::custom)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<(), A::Error> {
        // Also create groups whose source array is empty.
        (self.sink)(Some(&self.key), Row::default()).map_err(de::Error::custom)?;
        while let Some(row) = seq.next_element::<Row>()? {
            (self.sink)(Some(&self.key), row).map_err(de::Error::custom)?;
        }
        Ok(())
    }
}

fn text_reader(path: &Path) -> Result<Box<dyn Read>, String> {
    let mut file = File::open(path).map_err(|e| e.to_string())?;
    let mut prefix = [0u8; 3];
    let size = file.read(&mut prefix).map_err(|e| e.to_string())?;
    let mut utf8 = true;
    // Validate one line at a time; do not read an entire dictionary into memory.
    file.rewind().map_err(|e| e.to_string())?;
    if !prefix[..size].starts_with(&[0xff, 0xfe]) && !prefix[..size].starts_with(&[0xfe, 0xff]) {
        let mut reader = BufReader::new(&mut file);
        let mut line = Vec::new();
        loop {
            line.clear();
            if reader
                .read_until(b'\n', &mut line)
                .map_err(|e| e.to_string())?
                == 0
            {
                break;
            }
            if std::str::from_utf8(&line).is_err() {
                utf8 = false;
                break;
            }
        }
    }
    file.rewind().map_err(|e| e.to_string())?;
    let encoding = if prefix[..size].starts_with(&[0xff, 0xfe]) {
        UTF_16LE
    } else if prefix[..size].starts_with(&[0xfe, 0xff]) {
        UTF_16BE
    } else if utf8 {
        UTF_8
    } else {
        SHIFT_JIS
    };
    Ok(Box::new(
        DecodeReaderBytesBuilder::new()
            .encoding(Some(encoding))
            .build(file),
    ))
}

pub fn read(path: &Path, sink: &mut Sink<'_>) -> Result<(), String> {
    let suffix = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_lowercase();
    match suffix.as_str() {
        "json" => {
            let file = File::open(path).map_err(|e| e.to_string())?;
            let mut decoder = serde_json::Deserializer::from_reader(BufReader::new(file));
            ImportSeed { sink, group: None }
                .deserialize(&mut decoder)
                .map_err(|e| e.to_string())?;
            decoder.end().map_err(|e| e.to_string())
        }
        "csv" => {
            let mut reader = csv::ReaderBuilder::new()
                .has_headers(false)
                .flexible(true)
                .from_reader(text_reader(path)?);
            for result in reader.records() {
                let row = result.map_err(|e| e.to_string())?;
                sink(
                    None,
                    Row {
                        reading: row.get(0).unwrap_or("").into(),
                        word: row.get(1).unwrap_or("").into(),
                        pos: row.get(2).unwrap_or("名詞").into(),
                        comment: row.get(3).unwrap_or("").into(),
                    },
                )?;
            }
            Ok(())
        }
        "txt" => {
            for line in BufReader::new(text_reader(path)?).lines() {
                let line = line.map_err(|e| e.to_string())?;
                let line = line.trim();
                if line.is_empty() || line.starts_with(['!', '#']) {
                    continue;
                }
                let mut columns = line.split('\t');
                let reading = columns.next().unwrap_or("");
                let Some(word) = columns.next() else { continue };
                sink(
                    None,
                    Row {
                        reading: reading.into(),
                        word: word.into(),
                        pos: columns.next().unwrap_or("名詞").into(),
                        comment: columns.next().unwrap_or("").into(),
                    },
                )?;
            }
            Ok(())
        }
        _ => Err("JSON・CSV・TXTファイルを指定してください。".into()),
    }
}
