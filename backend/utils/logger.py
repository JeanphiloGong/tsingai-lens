import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from logging.handlers import TimedRotatingFileHandler
from config import LOG_DIR

# 创建目录
LOG_DIR.mkdir(parents=True, exist_ok=True)

def setup_logger(name=__name__):
    """
    创建并配置日志记录器，每天生成新的日志文件
    
    Args:
        name (str): 记录器名称（通常使用 __name__）
    
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # 捕获所有级别日志

    # 日志格式
    formatter = logging.Formatter(
        "%(asctime)s | %(name)-24s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    debug_file_handler = TimedRotatingFileHandler(
        filename=LOG_DIR / "app_debug.log",
        when="midnight",
        interval=1,
        encoding="utf-8"
    )
    debug_file_handler.setLevel(logging.DEBUG)
    debug_file_handler.setFormatter(formatter)
    debug_file_handler.suffix = "%Y-%m-%d"

    info_file_handler = TimedRotatingFileHandler(
        filename=LOG_DIR / "app_info.log",
        when="midnight",
        interval=1,
        encoding="utf-8"
    )
    info_file_handler.setLevel(logging.INFO)
    info_file_handler.setFormatter(formatter)
    info_file_handler.suffix = "%Y-%m-%d"

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    handlers = [debug_file_handler, info_file_handler, console_handler]

    # 将处理器挂到 root，保证所有子 logger（如 controllers.*）的日志都能输出
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    def _handler_exists(candidate: logging.Handler) -> bool:
        for existing in root_logger.handlers:
            if type(existing) is not type(candidate):
                continue
            if isinstance(candidate, TimedRotatingFileHandler):
                if getattr(existing, "baseFilename", None) == getattr(candidate, "baseFilename", None):
                    return True
            elif isinstance(candidate, logging.StreamHandler):
                if getattr(existing, "stream", None) is getattr(candidate, "stream", None):
                    return True
        return False

    for handler in handlers:
        if not _handler_exists(handler):
            root_logger.addHandler(handler)

    logging.captureWarnings(True)

    return logger

# 创建全局默认记录器
logger = setup_logger("main")
