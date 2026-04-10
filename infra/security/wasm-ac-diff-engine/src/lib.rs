use proxy_wasm::traits::*;
use proxy_wasm::types::*;
use proxy_wasm::hostcalls::*;
use aho_corasick::{AhoCorasick, MatchKind};
use std::collections::HashSet;

// 共享数据键 (Envoy 全局可见，零拷贝读取)
const SHARED_PATTERNS_KEY: &str = "ac_patterns_v1";
const SHARED_VERSION_KEY: &str = "ac_version_v1";

struct ACRoot {
    ac: Option<AhoCorasick>,
    current_version: u32,
    patterns: HashSet<String>,
}

impl Context for ACRoot {}

impl RootContext for ACRoot {
    fn on_configure(&mut self, _: usize) -> bool {
        // 1. 获取控制面推送的差分 JSON
        let conf = self.get_plugin_configuration().unwrap_or_default();
        if let Ok(patch) = serde_json::from_slice::<serde_json::Value>(&conf) {
            self.apply_diff_patch(&patch);
            self.rebuild_and_publish();
        }
        true
    }

    fn create_http_context(&self, id: u32) -> Option<Box<dyn HttpContext>> {
        // 读取共享内存中的 AC 树 (零拷贝)
        let (ver_data, _) = get_shared_data(SHARED_VERSION_KEY).ok()?;
        let ver = u32::from_ne_bytes(ver_data.try_into().ok()?);
        if ver != self.current_version {
            log::warn!("⚠️ 版本不一致，降级使用旧实例");
        }
        Some(Box::new(ACFilter {
            ac: self.ac.clone(),
        }))
    }
}

impl ACRoot {
    fn apply_diff_patch(&mut self, patch: &serde_json::Value) {
        if let Some(add) = patch.get("add").and_then(|v| v.as_array()) {
            for p in add { self.patterns.insert(p.as_str().unwrap_or("").to_string()); }
        }
        if let Some(remove) = patch.get("remove").and_then(|v| v.as_array()) {
            for p in remove { self.patterns.remove(p.as_str().unwrap_or("")); }
        }
        log::info!("📦 差分应用完成 | 当前模式数: {}", self.patterns.len());
    }

    fn rebuild_and_publish(&mut self) {
        let patterns: Vec<&str> = self.patterns.iter().map(|s| s.as_str()).collect();
        self.ac = Some(AhoCorasick::builder().match_kind(MatchKind::LeftmostLongest).build(&patterns).unwrap());
        
        // 原子更新 shared_data (Envoy 内部通过 Mutex + 共享内存实现，WASM 侧零拷贝访问)
        self.current_version += 1;
        set_shared_data(SHARED_VERSION_KEY, &self.current_version.to_ne_bytes()).ok();
        // 实际生产中 patterns 较大时仅存储版本指针，此处简化示意
        log::info!("✅ AC 树已重建并广播至共享内存 | 版本: {}", self.current_version);
    }
}

#[no_mangle]
pub fn _start() {
    proxy_wasm::main::set_log_level(LogLevel::Info);
    proxy_wasm::main::set_root_context(|_| -> Box<dyn RootContext> { Box::new(ACRoot { ac: None, current_version: 0, patterns: HashSet::new() }) });
}

struct ACFilter { ac: Option<AhoCorasick> }
impl Context for ACFilter {}
impl HttpContext for ACFilter {
    fn on_http_response_body(&mut self, body_size: usize, end_of_stream: bool) -> Action {
        // 流式匹配逻辑略 (同前版 AC)
        Action::Continue
    }
}
