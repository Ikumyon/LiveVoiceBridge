use crate::types::MetricsSnapshot;

/// プラットフォーム別のメトリクス収集インターフェース (Trait)
pub trait MetricsProvider: Send + Sync {
    /// システムリソースメトリクスを収集してスナップショットを返す
    fn collect(&mut self) -> MetricsSnapshot;
}
