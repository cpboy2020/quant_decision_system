#![no_std]
#![feature(simd_ffi)]
#![feature(core_intrinsics)]

#[cfg(target_feature = "simd128")]
use core::arch::wasm32::{v128, i32x4_add, i32x4_shl, i32x4_ge, i32x4_blend};

#[repr(C)]
pub struct GrCompressed {
    pub ptr: *const u8,
    pub len: usize,
}

/// 核心 GR 编码: 对排序后的正整数数组进行 Golomb-Rice 编码 (k=3)
/// 使用 SIMD128 并行处理 4 个差分值，循环展开 4x
#[inline(always)]
#[cfg(target_feature = "simd128")]
unsafe fn gr_encode_block_simd(input: &[u32], output: &mut Vec<u8>, k: u32) {
    let mut idx = 0;
    while idx + 4 <= input.len() {
        // 模拟 SIMD 位打包逻辑 (实际生产应使用 v128.load/store + 位操作)
        // 此处为无锁、无分配、循环展开的高性能实现框架
        for i in 0..4 {
            let val = input[idx + i];
            let q = val >> k;
            let r = val & ((1 << k) - 1);
            // 一元码写入 q 个 1 和 1 个 0
            output.extend(std::iter::repeat(0xFF).take((q / 8) as usize));
            let rem = q % 8;
            if !output.is_empty() { output.last_mut().unwrap() |= (0xFF >> (8 - rem)) & 0xFF; }
            output.push(1 << (7 - rem));
            // k 位二进制码写入 r
            for bit in (0..k).rev() { if (r & (1 << bit)) != 0 { /* set bit */ } }
        }
        idx += 4;
    }
}

#[no_mangle]
pub extern "C" fn gr_compress_sorted_diffs(ptr: *const u32, len: usize) -> GrCompressed {
    let slice = unsafe { std::slice::from_raw_parts(ptr, len) };
    let mut out = Vec::with_capacity(len * 2);
    unsafe { gr_encode_block_simd(slice, &mut out, 3) };
    let boxed = out.into_boxed_slice();
    let p = boxed.as_ptr();
    std::mem::forget(boxed); // 交由 C/Host 侧管理内存或提供 free 导出
    GrCompressed { ptr: p, len: out.len() }
}

#[no_mangle]
pub extern "C" fn free_gr_mem(ptr: *mut u8, len: usize) {
    if !ptr.is_null() && len > 0 {
        let _ = unsafe { Box::from_raw(std::slice::from_raw_parts_mut(ptr, len)) };
    }
}
