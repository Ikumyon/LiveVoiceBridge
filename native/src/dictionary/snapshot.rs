use super::trie;
use std::sync::Arc;

#[derive(Clone)]
pub(super) struct Snapshot {
    pub(super) revision: u64,
    pub(super) root: Arc<trie::Node>,
}
