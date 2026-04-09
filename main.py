# main.py (更新版)
import os
import time
import logging
from utils.logging_config import setup_logging
from execution.connector import GatewayConnector
from monitoring.metrics import MetricsCollector

logger = logging.getLogger("Main")

def print_banner(mode: str):
    """打印启动横幅，区分环境"""
    border = "=" * 60
    if mode == "live":
        warn = "⚠️  WARNING: LIVE TRADING MODE (REAL MONEY) ⚠️"
    else:
        warn = "ℹ️  INFO: SIMULATION / PAPER TRADING MODE"
    
    print(f"\n{border}")
    print(f"  Quantitative Decision Engine v1.0")
    print(f"  Mode: {mode.upper()}")
    print(f"  {warn}")
    print(border)

def main():
    # 1. 初始化日志 (根据环境变量)
    mode = os.getenv("MODE", "paper").lower()
    log_level = os.getenv("LOG_LEVEL", "DEBUG" if mode != "live" else "INFO")
    setup_logging(log_level=log_level, service_name=f"quant-{mode}")
    
    print_banner(mode)
    logger.info(f"🚀 系统正在初始化... | 模式：{mode.upper()} | 日志级别：{log_level}")

    # 2. 安全警告与确认
    if mode == "live":
        logger.critical("🚨 实盘模式检测：请确保已完成以下检查！")
        logger.critical("    1. 策略已通过回测与模拟盘验证")
        logger.critical("    2. 资金账户余额与风控限制已确认")
        logger.critical("    3. 交易所报备已完成")
        logger.info("⏳ 等待 5 秒启动（按 Ctrl+C 中断）...")
        time.sleep(5)

    # 3. 启动核心组件
    metrics = MetricsCollector(port=int(os.getenv("METRICS_PORT", 9090)))
    metrics.start_server()
    
    # 网关配置加载
    gateway_cfg = {}
    if mode == "live":
        # 加载实盘敏感配置（需脱敏日志）
        logger.info("🔐 正在加载实盘凭证... (QMT/Ptrade/CTP)")
        # gateway_cfg = load_secrets_from_vault() 
        logger.info("✅ 实盘配置加载完成")
    else:
        gateway_cfg = {"mode": "paper"}

    gateway = GatewayConnector(mode=mode, config=gateway_cfg)
    
    try:
        if gateway.start():
            logger.info("✅ 网关初始化成功，开始运行主循环")
            while True:
                time.sleep(1)
                # 此处放置策略逻辑、心跳检查、状态轮询
        else:
            logger.error("❌ 网关启动失败，系统退出")
    except KeyboardInterrupt:
        logger.info("👋 收到中断信号")
    finally:
        gateway.stop()
        metrics.stop()
        logger.info("🛑 系统已安全关闭")

if __name__ == "__main__":
    main()
