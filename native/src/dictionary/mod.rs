//! Portable SQLite storage, sparse editing drafts and immutable speech snapshots.
mod bindings;
mod database;
mod draft;
mod import;
mod snapshot;
#[cfg(test)]
mod tests;
mod trie;

pub use bindings::{DictionaryDatabase, DictionarySnapshot};

pub(super) type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;
pub(super) type GroupRow = (i64, String, usize, u64);
pub(super) type EntryRow = (i64, i64, String, String, String, String);
pub(super) type Page = (u64, Vec<EntryRow>);
