// 替换原 wasm_ac_persistence/wasm_ac_fast_init.rs 中的 on_configure
use std::fs;
use crate::fb_ac_serializer;

impl RootContext for ACRoot {
    fn on_configure(&mut self, _: usize) -> bool {
        // 优先从 FlatBuffers 冷快照恢复 (零分配)
        if !self.recovery_loaded {
            if let Ok(data) = fs::read("/wasm-cache/ac_snapshot_v2.fb") {
                match unsafe { fb_ac_serializer::load_snapshot_zero_copy(&data) } {
                    Ok(patterns) => {
                        log::info!("⚡ FB 零拷贝恢复 | 模式数: {}", patterns.len());
                        self.patterns = patterns.into_iter().map(|s| s.to_string()).collect();
                        self.recovery_loaded = true;
                    }
                    Err(e) => log::warn!("⚠️ FB 快照损坏: {}", e),
                }
            }
        }
        // ... 原有热推送逻辑 ...
        true
    }
}
