use proxy_wasm::traits::*;
use proxy_wasm::types::*;
use regex::Regex;
use lazy_static::lazy_static;
use std::cell::RefCell;

lazy_static! {
    // ✅ 允许列表: 审计核心 + 关键下游请求 + 直方图桶
    static ref ALLOW_LIST: Regex = Regex::new(
        r"^(audit_(requests_total|errors_total|latency_us_bucket|latency_us_sum|latency_us_count)|envoy_http_downstream_rq_(total|active)|# TYPE|# HELP)"
    ).unwrap();
}

#[derive(Clone)]
pub struct MetricPruneFilter {
    context_id: u32,
    path: RefCell<Option<String>>,
    body: RefCell<Vec<u8>>,
}

impl Context for MetricPruneFilter {}

#[no_mangle]
pub fn _start() {
    proxy_wasm::main::set_log_level(LogLevel::Info);
    proxy_wasm::main::set_root_context(|_| -> Box<dyn RootContext> { Box::new(Root) });
}

struct Root;
impl Context for Root {}
impl RootContext for Root {
    fn create_http_context(&self, ctx_id: u32) -> Option<Box<dyn HttpContext>> {
        Some(Box::new(MetricPruneFilter {
            context_id: ctx_id,
            path: RefCell::new(None),
            body: RefCell::new(Vec::new()),
        }))
    }
    fn get_type(&self) -> Option<ContextType> { Some(ContextType::HttpContext) }
}

impl HttpContext for MetricPruneFilter {
    fn on_http_request_headers(&mut self, _: usize, _: bool) -> Action {
        let path = self.get_http_request_header(":path").unwrap_or_default();
        *self.path.borrow_mut() = Some(path);
        Action::Continue
    }

    fn on_http_response_headers(&mut self, _: usize, _: bool) -> Action {
        let path = self.path.borrow().as_deref().unwrap_or("");
        if path.ends_with("/stats/prometheus") {
            // 移除 Content-Length, 由 Envoy 重新计算
            self.set_http_response_header("content-length", None);
            log::info!("🔍 拦截 /stats/prometheus, 启动流式裁剪...");
        }
        Action::Continue
    }

    fn on_http_response_body(&mut self, body_size: usize, end_of_stream: bool) -> Action {
        let path = self.path.borrow().as_deref().unwrap_or("");
        if !path.ends_with("/stats/prometheus") { return Action::Continue; }

        let mut buf = self.body.borrow_mut();
        let chunk = self.get_http_response_body(0, body_size).unwrap_or_default();
        buf.extend_from_slice(&chunk);

        if end_of_stream {
            let raw = String::from_utf8_lossy(&buf);
            let mut pruned = String::new();
            
            // 流式行过滤, 内存友好
            for line in raw.lines() {
                if ALLOW_LIST.is_match(line) || line.is_empty() || line.starts_with('#') {
                    pruned.push_str(line);
                    pruned.push_str("\r\n");
                }
            }
            
            let new_bytes = pruned.as_bytes();
            log::info!("✂️ 指标裁剪完成 | 原始: {}B -> 裁剪: {}B (压缩率 {:.1}%)", 
                       body_size, new_bytes.len(), (1.0 - new_bytes.len() as f32 / body_size as f32) * 100.0);
            
            self.set_http_response_body(0, body_size, new_bytes);
        }
        Action::Continue
    }
}
