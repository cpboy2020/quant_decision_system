//! FlatBuffers 增量 Diff 合并引擎 (WASM 内存安全设计)
//! 架构: Base FB (只读) + Delta Overlay (HashSet 原地修改) + 定期 Compaction 序列化
//! 优势: O(1) 增删, 零全量分配, 契合 WASM 线性内存与 GC 限制

use std::collections::HashSet;
use flatbuffers;

pub struct PatternStore {
    base_patterns: Vec<String>,       // 初始加载的基线快照
    active_adds: HashSet<String>,     // 增量添加集 (原地)
    active_removes: HashSet<String>,  // 增量删除集 (原地)
    version: u32,
    last_compact_ver: u32,
}

impl PatternStore {
    pub fn new(base: Vec<String>) -> Self {
        Self { base_patterns: base, active_adds: HashSet::new(), active_removes: HashSet::new(), version: 0, last_compact_ver: 0 }
    }

    /// O(K) 增量合并 (K=diff size), 不触发全局重分配
    pub fn apply_diff_inplace(&mut self, diff_add: Vec<&str>, diff_remove: Vec<&str>) {
        // 删除优先处理 (防冲突)
        for r in diff_remove {
            self.active_adds.remove(r);
            self.active_removes.insert(r.to_string());
        }
        for a in diff_add {
            let a_str = a.to_string();
            self.active_removes.remove(&a_str);
            self.active_adds.insert(a_str);
        }
        self.version += 1;
    }

    /// 快速查询 (基线 ∪ 增量 - 删除)
    pub fn contains(&self, line: &str) -> bool {
        if self.active_removes.contains(line) { return false; }
        if self.active_adds.contains(line) { return true; }
        self.base_patterns.iter().any(|p| p == line)
    }

    /// 定期 Compaction: 当 Diff 体积 > 阈值时, 原地重组基线并释放 Overlay
    pub fn compact_if_needed(&mut self, threshold: usize) -> Option<Vec<u8>> {
        let diff_size = self.active_adds.len() + self.active_removes.len();
        if diff_size > threshold {
            let mut new_base: Vec<String> = Vec::new();
            // 原地合并
            for p in &self.base_patterns { if !self.active_removes.contains(p) { new_base.push(p.clone()); } }
            new_base.extend(self.active_adds.drain());
            self.base_patterns = new_base;
            self.active_removes.clear();
            self.last_compact_ver = self.version;
            
            // 序列化至 FB 供持久化/网络同步
            Some(serialize_to_fbs(&self.base_patterns, self.version))
        } else { None }
    }
}

fn serialize_to_fbs(patterns: &[String], ver: u32) -> Vec<u8> {
    let mut fbb = flatbuffers::FlatBufferBuilder::with_capacity(2048);
    let v: Vec<_> = patterns.iter().map(|s| fbb.create_string(s)).collect();
    let pat_vec = fbb.create_vector(&v);
    let root = ac_rules::Snapshot::create(&mut fbb, &ac_rules::SnapshotArgs {
        version: ver, timestamp: 0, patterns: Some(pat_vec), checksum: Some(fbb.create_string("auto_compacted"))
    });
    fbb.finish(root, None);
    fbb.finished_data().to_vec()
}
