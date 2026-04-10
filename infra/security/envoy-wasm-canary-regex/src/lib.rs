use proxy_wasm::traits::*;
use proxy_wasm::types::*;
use regex::RegexSet;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use serde_json::Value;

#[derive(Clone)]
pub struct CanaryPruner {
    stable_set: Option<RegexSet>,
    canary_set: Option<RegexSet>,
    canary_ratio: u32,
    context_id: u32,
    buf: Vec<u8>,
    is_prom: bool,
}

fn hash_metric(name: &str) -> u32 {
    let mut h = DefaultHasher::new();
    name.hash(&mut h);
    h.finish() as u32 % 100
}

impl Context for CanaryPruner {}

#[no_mangle]
pub fn _start() {
    proxy_wasm::main::set_log_level(LogLevel::Info);
    proxy_wasm::main::set_root_context(|_| -> Box<dyn RootContext> { Box::new(Root {}) });
}

struct Root;
impl Context for Root {}
impl RootContext for Root {
    fn on_configure(&mut self, _: usize) -> bool {
        if let Some(conf) = self.get_plugin_configuration() {
            let v: Value = serde_json::from_slice(&conf).unwrap_or_default();
            // 配置格式: {"stable":["audit_.*","envoy_http.*"],"canary":[".*_new"],"canary_ratio":15}
            log::info!("🔄 灰度配置已热加载 | Canary Ratio: {}%", v["canary_ratio"].as_u64().unwrap_or(0));
        }
        true
    }
    fn create_http_context(&self, id: u32) -> Option<Box<dyn HttpContext>> {
        Some(Box::new(CanaryPruner {
            context_id: id, stable_set: None, canary_set: None,
            canary_ratio: 15, buf: Vec::new(), is_prom: false,
        }))
    }
}

impl CanaryPruner {
    fn match_line(&self, line: &str) -> bool {
        if line.is_empty() || line.starts_with('#') || line.starts_with("envoy_") || line.starts_with("audit_") { return true; }
        let h = hash_metric(line.split_whitespace().next().unwrap_or(""));
        let use_canary = h < self.canary_ratio;
        let set = if use_canary { &self.canary_set } else { &self.stable_set };
        match set {
            Some(r) => r.is_match(line),
            None => true // 默认放行
        }
    }
}

impl HttpContext for CanaryPruner {
    fn on_http_response_headers(&mut self, _: usize, _: bool) -> Action {
        if let Some(path) = self.get_http_response_header(":path") {
            if path.ends_with("/stats/prometheus") { self.is_prom = true; self.set_http_response_header("content-length", None); }
        }
        Action::Continue
    }

    fn on_http_response_body(&mut self, body_size: usize, eos: bool) -> Action {
        if !self.is_prom { return Action::Continue; }
        self.buf.extend(self.get_http_response_body(0, body_size).unwrap_or_default());
        if eos {
            let raw = String::from_utf8_lossy(&self.buf);
            let mut out = String::new();
            for line in raw.lines() { if self.match_line(line) { out += line; out += "\n"; } }
            self.set_http_response_body(0, body_size, out.as_bytes());
        }
        Action::Continue
    }
}
