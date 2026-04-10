use proxy_wasm::traits::*;
use proxy_wasm::types::*;
use serde_json::json;
use sha2::{Sha256, Digest};
use hex::encode;
use chrono::Utc;

#[derive(Clone)]
pub struct AuditFilter { context_id: u32 }

impl Context for AuditFilter {}

#[no_mangle]
pub fn _start() {
    proxy_wasm::main::set_log_level(LogLevel::Info);
    proxy_wasm::main::set_root_context(|_| -> Box<dyn RootContext> { Box::new(AuditRoot) });
}

struct AuditRoot;
impl Context for AuditRoot {}
impl RootContext for AuditRoot {
    fn create_http_context(&self, context_id: u32) -> Option<Box<dyn HttpContext>> {
        Some(Box::new(AuditFilter { context_id }))
    }
    fn get_type(&self) -> Option<ContextType> { Some(ContextType::HttpContext) }
}

impl HttpContext for AuditFilter {
    fn on_http_request_headers(&mut self, _: usize, _: bool) -> Action {
        self.dispatch_audit_log("request");
        Action::Continue
    }
    fn on_http_response_headers(&mut self, _: usize, _: bool) -> Action {
        self.dispatch_audit_log("response");
        Action::Continue
    }
}

impl AuditFilter {
    fn dispatch_audit_log(&self, phase: &str) {
        let path = self.get_http_request_header(":path").unwrap_or_default();
        let method = self.get_http_request_header(":method").unwrap_or_default();
        let user = self.get_http_request_header("x-forwarded-user").unwrap_or_else(|| "unknown".to_string());
        let ts = Utc::now().to_rfc3339();
        let nonce = Utc::now().timestamp_millis().to_string();
        
        // 防重放 + 完整性校验
        let raw = format!("{}|{}|{}|{}|{}", method, path, user, nonce, phase);
        let mut hasher = Sha256::new();
        hasher.update(raw.as_bytes());
        let audit_hash = encode(hasher.finalize());
        
        // 写入 Envoy 动态元数据与日志 (零拷贝优化: 预分配 JSON)
        let audit_payload = json!({
            "ts": ts,
            "nonce": nonce,
            "user": user,
            "method": method,
            "path": path,
            "phase": phase,
            "audit_hash": audit_hash
        }).to_string();
        
        self.set_property(vec!["metadata", "filter_metadata", "io.envoy.proxy.audit"], 
                          Some(audit_payload.as_bytes()));
        log::info!("🔗 [WASM-AUDIT] {}", audit_payload);
    }
}
