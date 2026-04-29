import logging
import os
from typing import Optional


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """获取或创建日志记录器。

    首次调用时配置 StreamHandler，后续调用返回已缓存的 logger 实例。
    日志级别由环境变量 ADVISOR_LOG_LEVEL 控制，默认 INFO。

    Args:
        name: 日志记录器名称，默认 "etf_quant_advisor"

    Returns:
        配置好的 logging.Logger 实例

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("初始化完成")
    """
    logger_name = name or "etf_quant_advisor"
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    log_level = os.getenv("ADVISOR_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(log_level)
    logger.propagate = False
    return logger
