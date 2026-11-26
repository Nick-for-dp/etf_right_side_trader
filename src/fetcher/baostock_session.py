"""管理 BaoStock 套接字生命周期并处理服务不可用问题。

上游客户端即使在 ``connect()`` 失败后，仍会把套接字保存到全局状态中，
随后继续使用这个未连接的套接字发送数据，从而在 Windows 上触发
WinError 10057。本封装会收敛客户端的冗余输出、设置套接字超时、清理
失效的全局连接，并在连接失败后临时熔断，避免单次 BaoStock 故障拖慢
每一个标的的数据采集。
"""

from __future__ import annotations

import io
import socket
import threading
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Iterator

import baostock as bs
import baostock.common.context as bs_context
from requests import RequestException


class BaoStockUnavailable(RequestException):
    """BaoStock 当前无法提供可用连接。"""


_session_lock = threading.RLock()
_unavailable_until = 0.0
_last_error = ""


def _close_stale_socket() -> None:
    """关闭并移除 BaoStock 模块全局上下文中残留的套接字。"""
    sock = getattr(bs_context, "default_socket", None)
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass
    if hasattr(bs_context, "default_socket"):
        delattr(bs_context, "default_socket")


def _format_client_output(buffer: io.StringIO) -> str:
    return " ".join(line.strip() for line in buffer.getvalue().splitlines() if line.strip())


def _open_circuit(message: str, cooldown: float) -> None:
    global _last_error, _unavailable_until
    _last_error = message
    _unavailable_until = time.monotonic() + cooldown


@contextmanager
def baostock_session(
    *,
    timeout: float = 8.0,
    cooldown: float = 60.0,
) -> Iterator[None]:
    """提供已登录的 BaoStock 会话，并限制套接字操作的等待时间。

    BaoStock 使用进程级全局套接字，因此整个会话通过锁保护。连接失败后，
    后续调用会在 ``cooldown`` 时间内快速失败，使应用能够立即切换到
    AKShare 备用数据源。
    """
    global _unavailable_until

    with _session_lock:
        remaining = _unavailable_until - time.monotonic()
        if remaining > 0:
            detail = _last_error or "连接失败"
            raise BaoStockUnavailable(
                f"BaoStock 暂时不可用（{remaining:.0f} 秒后重试）: {detail}"
            )

        client_output = io.StringIO()
        previous_timeout = socket.getdefaulttimeout()
        logged_in = False

        try:
            # bs.login() 创建的套接字会保留此超时设置，随后可安全恢复
            # 进程级默认超时时间。
            socket.setdefaulttimeout(timeout)
            with redirect_stdout(client_output), redirect_stderr(client_output):
                login_result = bs.login()
            socket.setdefaulttimeout(previous_timeout)

            if login_result.error_code != "0":
                detail = (
                    f"{login_result.error_code} {login_result.error_msg} "
                    f"{_format_client_output(client_output)}"
                ).strip()
                raise BaoStockUnavailable(detail)

            logged_in = True
            with redirect_stdout(client_output), redirect_stderr(client_output):
                yield
        except BaoStockUnavailable as exc:
            message = str(exc)
            _open_circuit(message, cooldown)
            raise
        except (ConnectionError, OSError, TimeoutError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            _open_circuit(message, cooldown)
            raise BaoStockUnavailable(message) from exc
        finally:
            socket.setdefaulttimeout(previous_timeout)
            if logged_in:
                try:
                    with redirect_stdout(client_output), redirect_stderr(client_output):
                        bs.logout()
                except Exception:
                    # 注销失败不能覆盖正常查询结果或原始连接异常。
                    pass
            _close_stale_socket()


def reset_baostock_circuit() -> None:
    """重置熔断状态，供测试和显式健康检查使用。"""
    global _last_error, _unavailable_until
    with _session_lock:
        _last_error = ""
        _unavailable_until = 0.0
        _close_stale_socket()
