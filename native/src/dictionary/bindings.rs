use super::{database::Store, import, snapshot::Snapshot, trie, EntryRow, GroupRow, Page, Result};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::path::Path;
use std::sync::{Arc, Mutex, RwLock};

#[pyclass(frozen)]
pub struct DictionarySnapshot {
    #[pyo3(get)]
    revision: u64,
    root: Arc<trie::Node>,
}

#[pymethods]
impl DictionarySnapshot {
    fn replace(&self, py: Python<'_>, text: &str) -> String {
        py.detach(|| self.root.replace(text))
    }
}

#[pyclass(frozen)]
pub struct DictionaryDatabase {
    store: Mutex<Store>,
    latest: Arc<RwLock<Snapshot>>,
}

impl DictionaryDatabase {
    fn run<T: Send>(
        &self,
        py: Python<'_>,
        operation: impl FnOnce(&mut Store) -> Result<T> + Send,
    ) -> PyResult<T> {
        py.detach(|| {
            let mut store = self
                .store
                .lock()
                .map_err(|_| PyValueError::new_err("辞書をロックできません。"))?;
            operation(&mut store).map_err(|e| PyValueError::new_err(e.to_string()))
        })
    }
}

#[pymethods]
impl DictionaryDatabase {
    #[new]
    fn new(py: Python<'_>, path: &str) -> PyResult<Self> {
        py.detach(|| {
            let store =
                Store::open(Path::new(path)).map_err(|e| PyValueError::new_err(e.to_string()))?;
            Ok(Self {
                latest: Arc::clone(&store.latest),
                store: Mutex::new(store),
            })
        })
    }

    fn snapshot(&self) -> PyResult<DictionarySnapshot> {
        let latest = self
            .latest
            .read()
            .map_err(|_| PyValueError::new_err("辞書を取得できません。"))?;
        Ok(DictionarySnapshot {
            revision: latest.revision,
            root: Arc::clone(&latest.root),
        })
    }

    fn begin(&self, py: Python<'_>) -> PyResult<u64> {
        self.run(py, Store::begin)
    }
    fn groups(&self, py: Python<'_>, draft: u64) -> PyResult<Vec<GroupRow>> {
        self.run(py, |s| s.groups(draft))
    }
    fn page(
        &self,
        py: Python<'_>,
        draft: u64,
        group: i64,
        offset: usize,
        limit: usize,
    ) -> PyResult<Page> {
        self.run(py, |s| s.page(draft, group, offset, limit))
    }
    fn add_group(&self, py: Python<'_>, draft: u64, name: &str) -> PyResult<i64> {
        self.run(py, |s| s.add_group(draft, name))
    }
    #[pyo3(signature=(draft, group, name=None))]
    fn edit_group(
        &self,
        py: Python<'_>,
        draft: u64,
        group: i64,
        name: Option<&str>,
    ) -> PyResult<()> {
        self.run(py, |s| s.edit_group(draft, group, name))
    }
    fn append(&self, py: Python<'_>, draft: u64, group: i64) -> PyResult<i64> {
        self.run(py, |s| s.append(draft, group, &import::Row::default()))
    }
    #[pyo3(signature=(draft, row, deleted=false))]
    fn edit(&self, py: Python<'_>, draft: u64, row: EntryRow, deleted: bool) -> PyResult<()> {
        self.run(py, |s| s.edit(draft, row, deleted))
    }
    fn import_file(&self, py: Python<'_>, draft: u64, group: i64, path: &str) -> PyResult<usize> {
        self.run(py, |s| s.import(draft, group, Path::new(path)))
    }
    fn commit(&self, py: Python<'_>, draft: u64) -> PyResult<()> {
        self.run(py, |s| s.commit(draft))
    }
    fn discard(&self, py: Python<'_>, draft: u64) -> PyResult<()> {
        self.run(py, |s| s.discard(draft))
    }
    #[pyo3(signature=(word, reading=None))]
    fn educate(&self, py: Python<'_>, word: &str, reading: Option<&str>) -> PyResult<()> {
        self.run(py, |s| s.educate(word, reading))
    }
}
