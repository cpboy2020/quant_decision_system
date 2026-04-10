// 追加至 envoy_audit_wasm/src/lib.rs 的 on_http_response_headers 中
// 使用 proxy-wasm 内置统计接口 (需 Envoy 1.20+)
use proxy_wasm::hostcalls;

fn record_audit_metrics(latency_us: u128, success: bool) {
    // 1. 计数器: 审计请求总数 / 失败数
    let success_str = if success { "success" } else { "error" };
    hostcalls::increment_counter("audit_requests_total", 1).ok();
    if !success { hostcalls::increment_counter("audit_errors_total", 1).ok(); }
    
    // 2. 直方图: 处理延迟 (单位: μs, buckets: 10, 50, 100, 250, 500, 1000)
    hostcalls::record_histogram("audit_latency_us", "histogram", latency_us).ok();
    
    // 3. Gauge: 当前活跃审计连接数 (可选)
    // hostcalls::set_gauge("audit_active_connections", 0); 
}
