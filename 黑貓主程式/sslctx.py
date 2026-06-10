"""
共用 SSL context 工廠。

verified_context() 用 certifi 的 CA bundle 做完整憑證驗證（frozen .app
打包後沒有系統憑證也能驗）；insecure_context() 只留給黑貓主機在實測
驗證失敗時的退路，GitHub 更新下載一律走 verified_context()。
"""

from __future__ import annotations

import ssl


def verified_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def insecure_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx
