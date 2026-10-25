use super::{database::Store, import, trie, EntryRow, GroupRow, Page, Result};
use rusqlite::{params, Connection, OptionalExtension};
use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;

impl Store {
    pub(super) fn check(&self, draft: u64) -> Result<()> {
        if self.draft != Some(draft) {
            return Err("辞書の編集セッションは終了しています。".into());
        }
        Ok(())
    }

    pub(super) fn begin(&mut self) -> Result<u64> {
        if self.draft.is_some() {
            return Err("辞書はすでに編集中です。".into());
        }
        let tx = self.db.transaction()?;
        tx.execute_batch(
            "
            DELETE FROM draft_entries; DELETE FROM draft_groups;
            INSERT INTO draft_groups(id,name,base_version) SELECT id,name,version FROM groups;",
        )?;
        tx.commit()?;
        self.generation += 1;
        self.next_id = -1;
        self.draft = Some(self.generation);
        Ok(self.generation)
    }

    pub(super) fn groups(&self, draft: u64) -> Result<Vec<GroupRow>> {
        self.check(draft)?;
        self.db.execute(
            "INSERT INTO draft_groups(id,name,base_version)
            SELECT id,name,version FROM groups WHERE id NOT IN(SELECT id FROM draft_groups)",
            [],
        )?;
        let revision = self
            .latest
            .read()
            .map_err(|_| "辞書を取得できません。")?
            .revision;
        let mut statement = self.db.prepare(
            "SELECT g.id,g.name,
            (SELECT COUNT(*) FROM entries e WHERE e.group_id=g.id
                AND NOT EXISTS(SELECT 1 FROM draft_entries d WHERE d.id=e.id))
            +(SELECT COUNT(*) FROM draft_entries d WHERE d.group_id=g.id AND d.deleted=0)
            FROM draft_groups g WHERE g.deleted=0 ORDER BY (g.id<0),
            CASE WHEN g.id<0 THEN -g.id ELSE g.id END",
        )?;
        let rows = statement.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, revision)))?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub(super) fn group_exists(&self, group: i64) -> Result<()> {
        if !self.db.query_row(
            "SELECT EXISTS(SELECT 1 FROM draft_groups WHERE id=? AND deleted=0)",
            [group],
            |r| r.get::<_, bool>(0),
        )? {
            return Err("辞書グループがありません。".into());
        }
        Ok(())
    }

    pub(super) fn page(&self, draft: u64, group: i64, offset: usize, limit: usize) -> Result<Page> {
        self.check(draft)?;
        self.group_exists(group)?;
        let mut statement = self.db.prepare("SELECT e.id,e.version,e.word,e.reading,e.pos,e.comment,e.id AS position
            FROM entries e WHERE e.group_id=?1 AND NOT EXISTS(SELECT 1 FROM draft_entries d WHERE d.id=e.id)
            UNION ALL SELECT id,base_version,word,reading,pos,comment,position
            FROM draft_entries WHERE group_id=?1 AND deleted=0
            ORDER BY position,id LIMIT ?2 OFFSET ?3")?;
        let rows = statement.query_map(params![group, limit.min(256), offset], |r| {
            Ok((
                r.get(0)?,
                r.get(1)?,
                r.get(2)?,
                r.get(3)?,
                r.get(4)?,
                r.get(5)?,
            ))
        })?;
        let revision = self
            .latest
            .read()
            .map_err(|_| "辞書を取得できません。")?
            .revision;
        Ok((revision, rows.collect::<rusqlite::Result<Vec<_>>>()?))
    }

    pub(super) fn add_group(&mut self, draft: u64, name: &str) -> Result<i64> {
        self.check(draft)?;
        let name = name.trim();
        if name.is_empty() {
            return Err("グループ名を指定してください。".into());
        }
        if self.db.query_row(
            "SELECT EXISTS(SELECT 1 FROM draft_groups WHERE name=? AND deleted=0)",
            [name],
            |r| r.get::<_, bool>(0),
        )? {
            return Err("同名のグループが存在します。".into());
        }
        let id = self.next_id;
        self.next_id -= 1;
        self.db.execute(
            "INSERT INTO draft_groups(id,name,base_version,changed) VALUES(?,?,-1,1)",
            params![id, name],
        )?;
        Ok(id)
    }

    pub(super) fn edit_group(&self, draft: u64, id: i64, name: Option<&str>) -> Result<()> {
        self.check(draft)?;
        self.group_exists(id)?;
        if let Some(name) = name {
            let name = name.trim();
            if name.is_empty() {
                return Err("グループ名を指定してください。".into());
            }
            if self.db.query_row(
                "SELECT EXISTS(SELECT 1 FROM draft_groups WHERE name=? AND id<>? AND deleted=0)",
                params![name, id],
                |r| r.get::<_, bool>(0),
            )? {
                return Err("同名のグループが存在します。".into());
            }
            self.db.execute(
                "UPDATE draft_groups SET name=?,changed=1 WHERE id=?",
                params![name, id],
            )?;
        } else {
            let count: usize = self.db.query_row(
                "SELECT COUNT(*) FROM draft_groups WHERE deleted=0",
                [],
                |r| r.get(0),
            )?;
            if count <= 1 {
                return Err("最後のグループは削除できません。".into());
            }
            self.db.execute(
                "UPDATE draft_groups SET deleted=1,changed=1 WHERE id=?",
                [id],
            )?;
        }
        Ok(())
    }

    pub(super) fn append(&mut self, draft: u64, group: i64, row: &import::Row) -> Result<i64> {
        self.check(draft)?;
        self.group_exists(group)?;
        let id = self.next_id;
        self.next_id -= 1;
        // Positive committed IDs precede all newly appended rows.
        let position = i64::MAX / 2 - id;
        let pos = if row.pos.trim().is_empty() {
            "名詞"
        } else {
            row.pos.trim()
        };
        self.db.execute(
            "INSERT INTO draft_entries(id,group_id,position,base_version,word,reading,pos,comment)
            VALUES(?,?,?,-1,?,?,?,?)",
            params![
                id,
                group,
                position,
                row.word.trim(),
                row.reading.trim(),
                pos,
                row.comment.trim()
            ],
        )?;
        Ok(id)
    }

    pub(super) fn edit(&self, draft: u64, row: EntryRow, deleted: bool) -> Result<()> {
        self.check(draft)?;
        let (id, version, word, reading, pos, comment) = row;
        let existing: bool = self.db.query_row(
            "SELECT EXISTS(SELECT 1 FROM draft_entries WHERE id=?)",
            [id],
            |r| r.get(0),
        )?;
        if !existing {
            let changed = self.db.execute("INSERT INTO draft_entries(id,group_id,position,base_version,word,reading,pos,comment)
                SELECT id,group_id,id,version,word,reading,pos,comment FROM entries WHERE id=? AND version=?", params![id,version])?;
            if changed == 0 {
                return Err(
                    "この単語は別の操作で変更されました。辞書を再読み込みしてください。".into(),
                );
            }
        }
        let pos = if pos.trim().is_empty() {
            "名詞"
        } else {
            pos.trim()
        };
        self.db.execute(
            "UPDATE draft_entries SET word=?,reading=?,pos=?,comment=?,deleted=? WHERE id=?",
            params![
                word.trim(),
                reading.trim(),
                pos,
                comment.trim(),
                deleted,
                id
            ],
        )?;
        Ok(())
    }

    pub(super) fn discard(&mut self, draft: u64) -> Result<()> {
        self.check(draft)?;
        let tx = self.db.transaction()?;
        tx.execute_batch("DELETE FROM draft_entries; DELETE FROM draft_groups;")?;
        tx.commit()?;
        self.draft = None;
        Ok(())
    }

    pub(super) fn import(&mut self, draft: u64, group: i64, path: &Path) -> Result<usize> {
        self.check(draft)?;
        self.group_exists(group)?;
        self.db.execute_batch("SAVEPOINT dictionary_import")?;
        let mut count = 0;
        let mut group_ids = HashMap::new();
        let result = import::read(path, &mut |name, row| {
            let result = (|| -> Result<()> {
                let target = if let Some(name) = name {
                    if let Some(id) = group_ids.get(name) {
                        *id
                    } else {
                        let existing = self
                            .db
                            .query_row(
                                "SELECT id FROM draft_groups WHERE name=? AND deleted=0",
                                [name],
                                |r| r.get(0),
                            )
                            .optional()?;
                        let id = match existing {
                            Some(id) => id,
                            None => self.add_group(draft, name)?,
                        };
                        group_ids.insert(name.to_owned(), id);
                        id
                    }
                } else {
                    group
                };
                if row.word.trim().is_empty() {
                    return Ok(());
                }
                if row.reading.trim().is_empty() {
                    return Err("読みが空の単語があります。".into());
                }
                self.append(draft, target, &row)?;
                count += 1;
                Ok(())
            })();
            result.map_err(|e| e.to_string())
        });
        match result {
            Ok(()) => {
                self.db.execute_batch("RELEASE dictionary_import")?;
                Ok(count)
            }
            Err(error) => {
                self.db
                    .execute_batch("ROLLBACK TO dictionary_import; RELEASE dictionary_import")?;
                Err(error.into())
            }
        }
    }

    pub(super) fn effective_reading(db: &Connection, word: &str) -> Result<Option<Arc<str>>> {
        let reading: Option<String> = db
            .query_row(
                "SELECT reading FROM entries WHERE word=?
            ORDER BY group_id DESC,id DESC LIMIT 1",
                [word],
                |r| r.get(0),
            )
            .optional()?;
        Ok(reading.map(Arc::from))
    }

    pub(super) fn commit(&mut self, draft: u64) -> Result<()> {
        self.check(draft)?;
        let tx = self.db.transaction()?;
        tx.execute_batch("DELETE FROM draft_entries WHERE group_id IN(SELECT id FROM draft_groups WHERE id<0 AND deleted=1);
            DELETE FROM draft_groups WHERE id<0 AND deleted=1;
            DELETE FROM draft_entries WHERE id<0 AND (deleted=1 OR word='');
            DELETE FROM draft_entries WHERE id>0 AND deleted=0 AND EXISTS(
                SELECT 1 FROM entries e WHERE e.id=draft_entries.id
                AND e.word=draft_entries.word AND e.reading=draft_entries.reading
                AND e.pos=draft_entries.pos AND e.comment=draft_entries.comment);
            UPDATE draft_groups SET changed=0 WHERE id>0 AND deleted=0
                AND name=(SELECT name FROM groups WHERE groups.id=draft_groups.id);")?;
        let conflict: bool = tx.query_row(
            "SELECT EXISTS(
            SELECT 1 FROM draft_groups d LEFT JOIN groups g ON g.id=d.id
            WHERE d.id>0 AND ((d.changed=1 AND (g.id IS NULL OR g.version<>d.base_version))
                OR (d.deleted=0 AND g.id IS NULL))
            UNION ALL SELECT 1 FROM draft_entries d LEFT JOIN entries e ON e.id=d.id
            WHERE d.id>0 AND (e.id IS NULL OR e.version<>d.base_version))",
            [],
            |r| r.get(0),
        )?;
        if conflict {
            return Err("編集中の単語またはグループが変更されました。キャンセルして辞書を再読み込みしてください。".into());
        }
        let invalid: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM draft_entries e JOIN draft_groups g ON g.id=e.group_id
            WHERE e.deleted=0 AND g.deleted=0 AND e.word<>'' AND e.reading='')",
            [],
            |r| r.get(0),
        )?;
        if invalid {
            return Err("読みが空の単語があります。".into());
        }
        tx.execute_batch("DELETE FROM affected_words;
            INSERT OR IGNORE INTO affected_words SELECT word FROM entries WHERE group_id IN(SELECT id FROM draft_groups WHERE deleted=1);
            INSERT OR IGNORE INTO affected_words SELECT e.word FROM entries e JOIN draft_entries d ON d.id=e.id;
            INSERT OR IGNORE INTO affected_words SELECT word FROM draft_entries;")?;
        let changed: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM draft_entries UNION ALL SELECT id FROM draft_groups WHERE changed=1)", [], |r| r.get(0))?;
        // Delete before renaming so a deleted group's name can be reused.
        tx.execute(
            "DELETE FROM groups WHERE id IN(SELECT id FROM draft_groups WHERE deleted=1)",
            [],
        )?;
        let groups: Vec<(i64, String)> = {
            let mut statement = tx.prepare(
                "SELECT id,name FROM draft_groups WHERE changed=1 AND deleted=0 ORDER BY id DESC",
            )?;
            let rows = statement.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?;
            rows.collect::<rusqlite::Result<_>>()?
        };
        let mut mapping = HashMap::new();
        // Use temporary unique names to allow group-name swaps.
        for (id, _) in &groups {
            if *id > 0 {
                let mut suffix = 0;
                let temporary = loop {
                    let name = format!("\u{1f}draft:{draft}:{id}:{suffix}");
                    let used: bool = tx.query_row(
                        "SELECT EXISTS(SELECT 1 FROM groups WHERE name=?1 UNION ALL SELECT 1 FROM draft_groups WHERE name=?1)",
                        [&name], |r| r.get(0),
                    )?;
                    if !used {
                        break name;
                    }
                    suffix += 1;
                };
                tx.execute(
                    "UPDATE groups SET name=? WHERE id=?",
                    params![temporary, id],
                )?;
            }
        }
        for (id, name) in &groups {
            if *id > 0 {
                tx.execute(
                    "UPDATE groups SET name=?,version=version+1 WHERE id=?",
                    params![name, id],
                )?;
            } else {
                tx.execute("INSERT INTO groups(name) VALUES(?)", [name])?;
                mapping.insert(*id, tx.last_insert_rowid());
            }
        }
        // Existing rows are updated in SQL without creating an application-side list.
        tx.execute_batch("UPDATE groups SET version=version+1 WHERE id IN(SELECT group_id FROM draft_entries);
            DELETE FROM entries WHERE id IN(SELECT id FROM draft_entries WHERE deleted=1 OR word='');
            UPDATE entries SET (word,reading,pos,comment)=(SELECT word,reading,pos,comment FROM draft_entries d WHERE d.id=entries.id),
                version=version+1 WHERE id IN(SELECT id FROM draft_entries WHERE deleted=0 AND word<>'');")?;
        {
            let mut statement = tx.prepare("SELECT d.group_id,d.word,d.reading,d.pos,d.comment FROM draft_entries d
                JOIN draft_groups g ON g.id=d.group_id WHERE d.id<0 AND d.deleted=0 AND d.word<>'' AND g.deleted=0
                ORDER BY d.id DESC")?;
            let mut rows = statement.query([])?;
            while let Some(row) = rows.next()? {
                let group: i64 = row.get(0)?;
                let group = *mapping.get(&group).unwrap_or(&group);
                tx.execute(
                    "INSERT INTO entries(group_id,word,reading,pos,comment) VALUES(?,?,?,?,?)",
                    params![
                        group,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?
                    ],
                )?;
            }
        }
        let current = self
            .latest
            .read()
            .map_err(|_| "辞書スナップショットを取得できません。")?
            .clone();
        let mut next = current.clone();
        if changed {
            let mut statement = tx.prepare("SELECT word FROM affected_words WHERE word<>''")?;
            let mut rows = statement.query([])?;
            while let Some(row) = rows.next()? {
                let word: String = row.get(0)?;
                trie::Node::update(&mut next.root, &word, Self::effective_reading(&tx, &word)?);
            }
            next.revision += 1;
            tx.execute("UPDATE metadata SET revision=? WHERE id=1", [next.revision])?;
        }
        tx.execute_batch(
            "DELETE FROM draft_entries; DELETE FROM draft_groups; DELETE FROM affected_words;",
        )?;
        // Take the publication lock before commit so a lock error cannot follow a successful save.
        let mut latest = self
            .latest
            .write()
            .map_err(|_| "辞書スナップショットを更新できません。")?;
        tx.commit()?;
        *latest = next;
        self.draft = None;
        Ok(())
    }
}
