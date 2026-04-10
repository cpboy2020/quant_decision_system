// 追加至 envoy_ac_diff_filter/src/lib.rs 的 on_start/on_configure
use std::fs;

struct ACRoot {
    // ... 原有字段
    recovery_loaded: bool,
}

impl RootContext for ACRoot {
    fn on_configure(&mut self, _: usize) -> bool {
        // 1. 优先尝试从冷启动卷读取 etcd 预载快照
        if !self.recovery_loaded {
            if let Ok(data) = fs::read("/wasm-cache/ac_snapshot_v1.json") {
                if let Ok(patch) = serde_json::from_slice(&data) {
                    self.apply_diff_patch(&patch);
                    self.recovery_loaded = true;
                    log::info("💾 冷启动快照恢复成功 | 跳过首次全量拉取");
                }
            }
        }
        
        // 2. 处理运行时热推送
        if let Some(data) = self.get_plugin_configuration() {
            if let Ok(patch) = serde_json::from_slice::<serde_json::Value>(&data) {
                self.apply_diff_patch(&patch);
                self.rebuild_and_publish();
            }
        }
        true
    }
}
