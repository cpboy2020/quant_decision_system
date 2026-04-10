#!/usr/bin/env python3
"""
Meta-RL 在线 A2C 微调管道: Kafka 流式采集 (s, a, r, s') → 异步梯度累积 → 原子权重热替换
架构: 训练线程(锁) ↔ 推理线程(读) | 零停机 | 指标暴露至 Prometheus
"""
import os, time, asyncio, logging, json, hashlib
from threading import Thread, Lock
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
import torch, torch.nn as nn, torch.optim as optim
import numpy as np
from prometheus_client import Gauge, Counter, start_http_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("A2C-OnlineTuner")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka-quant.svc:9092")
TOPIC_TRANSITIONS = "meta_rl_transitions"
TOPIC_CHECKPOINTS = "meta_rl_ckpts"
CKPT_PATH = "/data/meta_safety_latest.pt"

# Prometheus 指标
TRAIN_LOSS = Gauge("a2c_online_loss", "Current A2C loss")
WEIGHT_HASH = Gauge("model_weight_hash", "Truncated SHA256 of model weights")
UPDATE_FREQ = Counter("a2c_weight_updates", "Total weight hot-swap events")

class SafetyPolicy(nn.Module):
    def __init__(self): super().__init__()
        self.net = nn.Sequential(
            nn.Linear(5, 64), nn.ReLU(), nn.LayerNorm(64),
            nn.Linear(64, 64), nn.ReLU(), nn.Linear(64, 2), nn.Tanh()
        )
    def forward(self, x): return self.net(x)

class A2COnlineEngine:
    def __init__(self):
        self.model = SafetyPolicy()
        self.optimizer = optim.Adam(self.model.parameters(), lr=1e-3)
        self.model_lock = Lock()  # 读写锁保障推理/训练并发
        self.batch_buffer = []
        self.BATCH_SIZE = 64
        self.gamma = 0.99

    def _load_or_init(self):
        if os.path.exists(CKPT_PATH):
            self.model.load_state_dict(torch.load(CKPT_PATH, map_location="cpu"))
            log.info("✅ 加载最新权重快照")
        WEIGHT_HASH.set(self._calc_weight_hash())

    def _calc_weight_hash(self) -> float:
        state = self.model.state_dict()
        h = hashlib.sha256(str(state).encode()).hexdigest()
        return int(h[:8], 16) / 0xFFFFFFFF

    async def kafka_listener(self):
        consumer = AIOKafkaConsumer(TOPIC_TRANSITIONS, bootstrap_servers=KAFKA_BOOTSTRAP, auto_offset_reset="earliest")
        await consumer.start()
        try:
            async for msg in consumer:
                record = json.loads(msg.value.decode())
                self.batch_buffer.append(record)
                if len(self.batch_buffer) >= self.BATCH_SIZE:
                    self._train_step()
        finally: await consumer.stop()

    def _train_step(self):
        with self.model_lock:
            states = torch.tensor([b["state"] for b in self.batch_buffer], dtype=torch.float32)
            actions = torch.tensor([b["action"] for b in self.batch_buffer], dtype=torch.float32)
            rewards = torch.tensor([b["reward"] for b in self.batch_buffer], dtype=torch.float32)
            
            # 简化的 A2C 梯度计算 (Actor: 最大化对数概率×优势, Critic: 均方误差)
            values = self.model(states).squeeze()
            advantage = rewards - values.detach()
            loss_actor = -(advantage * (actions - values)).mean()
            loss_critic = ((rewards - values) ** 2).mean()
            loss = loss_actor + 0.5 * loss_critic
            
            self.optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=0.5)
            self.optimizer.step()
            
            TRAIN_LOSS.set(loss.item())
            self.batch_buffer.clear()

    def atomic_hot_swap(self):
        """推理服务调用：安全获取当前模型快照"""
        with self.model_lock:
            torch.save(self.model.state_dict(), CKPT_PATH)
            WEIGHT_HASH.set(self._calc_weight_hash())
            UPDATE_FREQ.inc()
        return self.model.state_dict()

    def run(self):
        self._load_or_init()
        start_http_server(9115, addr="0.0.0.0")
        log.info("🚀 A2C 在线微调引擎启动 | 监听 Topic: %s", TOPIC_TRANSITIONS)
        loop = asyncio.get_event_loop()
        loop.create_task(self.kafka_listener())
        try: loop.run_forever()
        except KeyboardInterrupt: log.info("⏹️ 优雅退出")

if __name__ == "__main__": A2COnlineEngine().run()
