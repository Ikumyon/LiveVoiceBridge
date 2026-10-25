use super::{database::Store, import};
use rusqlite::Connection;
use std::path::Path;

fn memory() -> Store {
    Store::initialize(Connection::open_in_memory().unwrap()).unwrap()
}

fn append(store: &mut Store, draft: u64, group: i64, word: &str, reading: &str) {
    store
        .append(
            draft,
            group,
            &import::Row {
                word: word.into(),
                reading: reading.into(),
                ..import::Row::default()
            },
        )
        .unwrap();
}

#[test]
fn drafts_are_sparse_ordered_bounded_and_discardable() {
    let mut store = memory();
    let draft = store.begin().unwrap();
    let group = store.groups(draft).unwrap()[0].0;
    for index in 0..600 {
        append(&mut store, draft, group, &format!("単語{index}"), "よみ");
    }
    assert_eq!(store.groups(draft).unwrap()[0].2, 600);
    let rows = store.page(draft, group, 0, 999).unwrap().1;
    assert_eq!(rows.len(), 256);
    assert_eq!(rows[0].2, "単語0");
    assert_eq!(
        store.page(draft, group, 599, 256).unwrap().1[0].2,
        "単語599"
    );
    assert_eq!(store.latest.read().unwrap().root.replace("単語0"), "単語0");
    store.commit(draft).unwrap();
    let draft = store.begin().unwrap();
    let mut row = store.page(draft, group, 0, 1).unwrap().1.remove(0);
    row.3 = "へんこう".into();
    store.edit(draft, row, false).unwrap();
    let count: usize = store
        .db
        .query_row("SELECT COUNT(*) FROM draft_entries", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 1);
    store.discard(draft).unwrap();
    assert_eq!(store.latest.read().unwrap().root.replace("単語0"), "よみ");
}

#[test]
fn deleting_a_group_restores_lower_priority_readings_and_keeps_old_snapshots() {
    let mut store = memory();
    let draft = store.begin().unwrap();
    let group = store.groups(draft).unwrap()[0].0;
    append(&mut store, draft, group, "東京", "とうきょう");
    let higher = store.add_group(draft, "優先").unwrap();
    append(&mut store, draft, higher, "東京", "とーきょー");
    store.commit(draft).unwrap();
    let previous = store.latest.read().unwrap().clone();
    assert_eq!(previous.root.replace("東京"), "とーきょー");
    let draft = store.begin().unwrap();
    let higher = store
        .groups(draft)
        .unwrap()
        .into_iter()
        .find(|g| g.1 == "優先")
        .unwrap()
        .0;
    store.edit_group(draft, higher, None).unwrap();
    store.commit(draft).unwrap();
    assert_eq!(
        store.latest.read().unwrap().root.replace("東京"),
        "とうきょう"
    );
    assert_eq!(previous.root.replace("東京"), "とーきょー");
}

#[test]
fn unrelated_education_is_preserved_but_same_entry_conflicts() {
    let mut store = memory();
    store.educate("東京", Some("とうきょう")).unwrap();
    let draft = store.begin().unwrap();
    let group = store
        .groups(draft)
        .unwrap()
        .into_iter()
        .find(|g| g.1 == "配信コメント")
        .unwrap()
        .0;
    let mut row = store.page(draft, group, 0, 1).unwrap().1.remove(0);
    row.3 = "とーきょー".into();
    store.edit(draft, row, false).unwrap();
    store.educate("大阪", Some("おおさか")).unwrap();
    store.commit(draft).unwrap();
    assert_eq!(
        store.latest.read().unwrap().root.replace("東京大阪"),
        "とーきょーおおさか"
    );
    let draft = store.begin().unwrap();
    let mut row = store.page(draft, group, 0, 1).unwrap().1.remove(0);
    row.3 = "別の読み".into();
    store.edit(draft, row, false).unwrap();
    store.educate("東京", Some("再教育")).unwrap();
    assert!(store.commit(draft).is_err());
    assert_eq!(store.draft, Some(draft));
    assert_eq!(store.latest.read().unwrap().root.replace("東京"), "再教育");
    store.discard(draft).unwrap();
}

#[test]
fn grouped_import_is_explicit_and_invalid_import_rolls_back_only_its_rows() {
    let mut store = memory();
    let draft = store.begin().unwrap();
    let group = store.groups(draft).unwrap()[0].0;
    append(&mut store, draft, group, "既存", "きそん");
    let fixtures = Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/dictionary");
    assert!(store
        .import(draft, group, &fixtures.join("invalid.json"))
        .is_err());
    assert_eq!(store.groups(draft).unwrap()[0].2, 1);
    assert_eq!(
        store
            .import(draft, group, &fixtures.join("grouped.json"))
            .unwrap(),
        2
    );
    let groups = store.groups(draft).unwrap();
    assert!(groups.iter().any(|g| g.1 == "空" && g.2 == 0));
    store.commit(draft).unwrap();
    assert_eq!(
        store.latest.read().unwrap().root.replace("既存東京都"),
        "きそんとうきょうと"
    );
}

#[test]
fn invalid_save_keeps_the_draft_and_unchanged_saves_keep_the_revision() {
    let mut store = memory();
    let draft = store.begin().unwrap();
    let group = store.groups(draft).unwrap()[0].0;
    append(&mut store, draft, group, "未完", "");
    assert!(store.commit(draft).is_err());
    assert_eq!(store.draft, Some(draft));
    assert_eq!(store.latest.read().unwrap().revision, 0);
    let mut row = store.page(draft, group, 0, 1).unwrap().1.remove(0);
    row.3 = "みかん".into();
    store.edit(draft, row, false).unwrap();
    store.commit(draft).unwrap();
    let revision = store.latest.read().unwrap().revision;
    let draft = store.begin().unwrap();
    let row = store.page(draft, group, 0, 1).unwrap().1.remove(0);
    store.edit(draft, row, false).unwrap();
    store.append(draft, group, &import::Row::default()).unwrap();
    store.commit(draft).unwrap();
    assert_eq!(store.latest.read().unwrap().revision, revision);
}
