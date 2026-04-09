import os
import logging
import logging.handlers
from datetime import datetime

def setup_logging(log_level: str = "INFO", log_dir: str = "logs", service_name: str = "quant-engine"):
    """
    配置分级日志：
    - 控制台：INFO 级别（生产模式默认）
    - 文件：DEBUG 级别（包含详细堆栈与数据载荷）
    - 策略：按日切割，保留 30 天
    """
    os.makedirs(log_dir, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 1. 格式化器 (包含模块名、函数名、行号，方便定位)
    log_format = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(funcName)s:%(lineno)d - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # 2. 控制台 Handler (Stream)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 3. 文件 Handler (TimedRotatingFile - 按天滚动)
    log_file = os.path.join(log_dir, f"{service_name}.log")
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",       # 每日 00:00 切割
        interval=1,
        backupCount=30,        # 保留 30 天
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)  # 文件记录全量 DEBUG
    file_handler.setFormatter(formatter)
    # 自动添加后缀如 .log.2026-04-09
    file_handler.suffix = "%Y-%m-%d"
    
    root_logger.addHandler(file_handler)

    # 4. 抑制第三方库噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # 5. 启动欢迎日志
    root_logger.info(f"📜 日志系统初始化完成 | 文件路径：{os.path.abspath(log_file)} | 级别：{log_level.upper()}")