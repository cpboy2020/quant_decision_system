// 集成至 wasm_ac_persistence 或 ac_diff_filter 的 Rust 模块
use std::slice;
use ac_rules::Snapshot;
use sha2::{Sha256, Digest};
use hex::encode;

// 1. 序列化 (控制面/etcd 侧)
pub fn serialize_snapshot_to_fbs(patterns: &[&str]) -> Vec<u8> {
    let mut builder = flatbuffers::FlatBufferBuilder::with_capacity(1024);
    let p_offsets: Vec<_> = patterns.iter().map(|s| builder.create_string(s)).collect();
    let p_vec = builder.create_vector(&p_offsets);
    
    let checksum = {
        let mut h = Sha256::new();
        for p in patterns { h.update(p.as_bytes()); }
        builder.create_string(&encode(h.finalize()))
    };

    let root = Snapshot::create(&mut builder, 
        &SnapshotArgs { version: 2, timestamp: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs(), patterns: Some(p_vec), checksum: Some(checksum) });
    builder.finish(root, None);
    builder.finished_data().to_vec()
}

// 2. 零拷贝反序列化 (WASM 冷启动侧)
pub unsafe fn load_snapshot_zero_copy(buf: &[u8]) -> Result<Vec<&str>, &'static str> {
    let root = flatbuffers::root::<Snapshot>(buf).map_err(|_| "Invalid FB header")?;
    if let Some(pat_vec) = root.patterns() {
        Ok(pat_vec.iter().collect())
    } else {
        Err("Empty patterns vector")
    }
}
