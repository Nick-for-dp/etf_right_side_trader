"""请求限速工具。

提供请求限速装饰器，控制请求频率，防止被封禁。
使用 tenacity 库实现强大的重试机制。
"""

import time
import threading
import functools
from typing import Callable, Dict, Tuple, Type

from requests import RequestException
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    wait_fixed,
    retry_if_exception_type,
    RetryError,
)

from src.utils import get_logger


logger = get_logger(__name__)
# 全局状态
_last_request_time: Dict[str, float] = {}
_request_lock = threading.Lock()
# 默认只重试网络相关异常
DEFAULT_RETRY_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    RequestException,
    RetryError,
)


def rate_limit(min_interval: float = 1.0, key: str = "default") -> Callable:
    """请求限速装饰器。

    基于时间间隔控制请求频率，确保两次请求之间有最小间隔。
    线程安全，支持多个独立的限速通道。

    Args:
        min_interval: 最小请求间隔（秒），默认 1.0 秒
        key: 限速通道标识，不同 key 独立计时

    Returns:
        装饰器函数

    Example:
        >>> @rate_limit(min_interval=1.0, key="eastmoney")
        ... def fetch_data():
        ...     return requests.get("https://example.com")
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with _request_lock:
                last_time = _last_request_time.get(key, 0)
                elapsed = time.time() - last_time

                if elapsed < min_interval:
                    wait_time = min_interval - elapsed
                    logger.info(f"限速等待 {wait_time:.2f} 秒 (key={key})")
                    time.sleep(wait_time)
                
            # 执行函数
            result = func(*args, **kwargs)
            # 函数执行完成后更新最后请求时间
            with _request_lock:
                _last_request_time[key] = time.time()

            return result

        return wrapper

    return decorator


def retry_on_error(
    max_retries: int = 3,
    retry_delay: float = 5.0,
    exceptions: Tuple[Type[Exception], ...] = DEFAULT_RETRY_EXCEPTIONS,
    use_exponential: bool = True,
    max_wait: float = 90.0,
) -> Callable:
    """重试装饰器（基于 tenacity 实现）。

    当函数抛出指定异常时自动重试，支持指数退避策略。

    Args:
        max_retries: 最大重试次数，默认 3 次
        retry_delay: 初始重试间隔（秒），默认 5.0 秒
        exceptions: 触发重试的异常类型元组
        use_exponential: 是否使用指数退避，默认 True
        max_wait: 最大等待时间（秒），默认 90 秒

    Returns:
        装饰器函数

    Example:
        >>> @retry_on_error(max_retries=3, retry_delay=2.0)
        ... def fetch_data():
        ...     return requests.get("https://example.com")
    """

    def decorator(func: Callable) -> Callable:
        # 配置等待策略
        if use_exponential:
            wait_strategy = wait_exponential(
                multiplier=retry_delay,
                min=retry_delay,
                max=max_wait,
            )
        else:
            wait_strategy = wait_fixed(retry_delay)

        @retry(
            stop=stop_after_attempt(max_retries + 1),
            wait=wait_strategy,
            retry=retry_if_exception_type(exceptions),
            reraise=True,
        )
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator
