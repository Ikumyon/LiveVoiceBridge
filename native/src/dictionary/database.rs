use super::{snapshot::Snapshot, trie, Result};
use rusqlite::{params, Connection};
use std::path::Path;
use std::sync::{Arc, RwLock};

pub(super) struct Store {
    pub(super) db: Connection,
    pub(super) draft: Option<u64>,
    pub(super) generation: u64,
    pub(super) next_id: i64,
    pub(super) latest: Arc<RwLock<Snapshot>>,
}

impl Store {
    pub(super) fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let db = Connection::open(path)?;
        Self::initialize(db)
    }

    pub(super) fn initialize(db: Connection) -> Result<Self> {
        db.execute_batch("
            PRAGMA foreign_keys=ON;
            PRAGMA cache_size=-8192;
            PRAGMA temp_store=MEMORY;
            PRAGMA journal_mode=DELETE;
            PRAGMA locking_mode=EXCLUSIVE;
            CREATE TABLE IF NOT EXISTS groups(
                id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,version INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS entries(
                id INTEGER PRIMARY KEY AUTOINCREMENT,group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
                word TEXT NOT NULL,reading TEXT NOT NULL,pos TEXT NOT NULL,comment TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS entries_group_order ON entries(group_id,id);
            CREATE INDEX IF NOT EXISTS entries_word_group ON entries(word,group_id,id);
            CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL);
            INSERT OR IGNORE INTO metadata VALUES(1,0);
            CREATE TABLE IF NOT EXISTS draft_groups(
                id INTEGER PRIMARY KEY,name TEXT NOT NULL,base_version INTEGER NOT NULL,
                changed INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS draft_entries(
                id INTEGER PRIMARY KEY,group_id INTEGER NOT NULL,position INTEGER NOT NULL,
                base_version INTEGER NOT NULL,word TEXT NOT NULL,reading TEXT NOT NULL,pos TEXT NOT NULL,
                comment TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS draft_group_order ON draft_entries(group_id,position);
            CREATE TABLE IF NOT EXISTS affected_words(word TEXT PRIMARY KEY);
            DELETE FROM affected_words;
            DELETE FROM draft_entries;
            DELETE FROM draft_groups;
            INSERT INTO groups(name) SELECT 'デフォルト' WHERE NOT EXISTS(SELECT 1 FROM groups);
        ")?;
        let mut root = Arc::new(trie::Node::default());
        {
            let mut statement =
                db.prepare("SELECT word,reading FROM entries ORDER BY group_id,id")?;
            let mut rows = statement.query([])?;
            while let Some(row) = rows.next()? {
                let word: String = row.get(0)?;
                let reading: String = row.get(1)?;
                trie::Node::update(&mut root, &word, Some(Arc::from(reading)));
            }
        }
        let revision =
            db.query_row("SELECT revision FROM metadata WHERE id=1", [], |r| r.get(0))?;
        Ok(Self {
            db,
            draft: None,
            generation: 0,
            next_id: -1,
            latest: Arc::new(RwLock::new(Snapshot { revision, root })),
        })
    }

    pub(super) fn educate(&mut self, word: &str, reading: Option<&str>) -> Result<()> {
        if word.is_empty() {
            return Err("単語を指定してください。".into());
        }
        let tx = self.db.transaction()?;
        tx.execute(
            "INSERT OR IGNORE INTO groups(name) VALUES('配信コメント')",
            [],
        )?;
        let group: i64 = tx.query_row(
            "SELECT id FROM groups WHERE name='配信コメント'",
            [],
            |r| r.get(0),
        )?;
        let (count, current): (usize, Option<String>) = tx.query_row(
            "SELECT COUNT(*),MIN(reading) FROM entries WHERE group_id=? AND word=?",
            params![group, word],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )?;
        if reading.is_none() && count == 0
            || reading.is_some_and(|r| count == 1 && current.as_deref() == Some(r))
        {
            tx.commit()?;
            return Ok(());
        }
        tx.execute(
            "DELETE FROM entries WHERE group_id=? AND word=?",
            params![group, word],
        )?;
        if let Some(reading) = reading {
            if reading.is_empty() {
                return Err("読みを指定してください。".into());
            }
            tx.execute("INSERT INTO entries(group_id,word,reading,pos,comment) VALUES(?,?,?,'名詞','コメント追加')", params![group,word,reading])?;
        }
        tx.execute("UPDATE groups SET version=version+1 WHERE id=?", [group])?;
        let mut next = self
            .latest
            .read()
            .map_err(|_| "辞書スナップショットを取得できません。")?
            .clone();
        trie::Node::update(&mut next.root, word, Self::effective_reading(&tx, word)?);
        next.revision += 1;
        tx.execute("UPDATE metadata SET revision=? WHERE id=1", [next.revision])?;
        let mut latest = self
            .latest
            .write()
            .map_err(|_| "辞書スナップショットを更新できません。")?;
        tx.commit()?;
        *latest = next;
        Ok(())
    }
}
