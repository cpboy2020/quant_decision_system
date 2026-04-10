#!/usr/bin/env python3
"""
Streamlit SRE 交互看板: 实时滑块调权 → WebSocket 推送 → 流量分布可视化
"""

import streamlit as st
import websockets
import asyncio
import json
import time
import pandas as pd

st.set_page_config(layout="wide", page_title="SRE Pareto 控制台")
st.title("🎛️ SRE 交互式 Pareto 流量权重控制台")
st.caption("拖拽滑块实时调整优化偏好，引擎将通过 WebSocket 自动收敛至新 Pareto 前沿")

WS_URI = os.getenv("PARETO_WS_URI", "ws://localhost:8005/ws/pareto")

if "ws" not in st.session_state:
    st.session_state.ws = None


async def init_ws():
    ws = await websockets.connect(WS_URI)
    return ws


# 侧边栏状态监控
with st.sidebar:
    st.header("📊 实时状态")
    st.session_state["ws"] = asyncio.get_event_loop().run_until_complete(init_ws())
    # 初始化权重 (首次或断线重连)
    if st.session_state.ws and st.session_state.ws.open:
        pass

col1, col2 = st.columns([2, 1])
with col1:
    w_ctr = st.slider("CTR/转化率权重 (w_ctr)", 0.1, 0.9, 0.6, step=0.05)
    w_lat = st.slider("延迟体验权重 (w_lat)", 0.05, 0.6, 0.25, step=0.05)
    w_err = st.slider("错误率惩罚权重 (w_err)", 0.05, 0.5, 0.15, step=0.05)

    # 归一化提示
    total = w_ctr + w_lat + w_err
    if abs(total - 1.0) > 0.01:
        st.warning(f"⚠️ 权重总和为 {total:.2f}, 引擎将自动归一化")

    if st.button("📤 应用权重"):
        weights = {"w_ctr": w_ctr, "w_lat": w_lat, "w_err": w_err}
        asyncio.get_event_loop().run_until_complete(
            st.session_state.ws.send(
                json.dumps({"type": "update_weights", "weights": weights})
            )
        )
        st.success("✅ 已推送至流控引擎")

with col2:
    st.subheader("🔄 流量实时分布")
    # 模拟实时拉取/WS接收
    df = pd.DataFrame(
        {"Arm": ["Control", "Variant A", "Variant B"], "Alloc": [0.45, 0.35, 0.20]}
    )
    st.bar_chart(
        df.set_index("Arm"), height=300, color=["#1E3A8A", "#3B82F6", "#93C5FD"]
    )
    st.metric("当前 κ (探索强度)", "2.4", "↑ 15%")
