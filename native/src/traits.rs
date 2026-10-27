use crate::types::{MetricsRequest, MetricsSnapshot};

/// プラットフォーム別のメトリクス収集インターフェース (Trait)
pub trait MetricsProvider: Send + Sync {
    /// システムリソースメトリクスを収集してスナップショットを返す
    fn set_request(&mut self, request: &MetricsRequest);
    fn collect(&mut self, request: &MetricsRequest) -> MetricsSnapshot;
    fn discover_gpus(&mut self) -> Vec<(String, String)>;
}
