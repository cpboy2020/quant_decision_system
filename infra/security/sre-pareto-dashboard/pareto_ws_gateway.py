#!/usr/bin/env python3
"""
FastAPI WebSocket 网关: 广播 SRE 调节的 Pareto 权重 → 实时生效至流控引擎
"""

import os
import json
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, Set
import asyncio

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
app = FastAPI()

manager = set()  # 存储 WebSocket 连接
current_weights = {"w_ctr": 0.6, "w_lat": 0.25, "w_err": 0.15}


@app.websocket("/ws/pareto")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    manager.add(websocket)
    try:
        # 推送当前权重
        await websocket.send_json({"type": "init", "weights": current_weights})
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "update_weights":
                current_weights.update(data["weights"])
                # 广播至所有面板
                msg = {"type": "update", "weights": dict(current_weights)}
                disconnected = set()
                for ws in manager:
                    try:
                        await ws.send_json(msg)
                    except:
                        disconnected.add(ws)
                manager.difference_update(disconnected)
                logging.info(f"📤 权重已同步: {current_weights}")
    except WebSocketDisconnect:
        manager.discard(websocket)


@app.get("/api/current_weights")
def get_weights():
    return {"weights": current_weights}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8005, log_level="info")
