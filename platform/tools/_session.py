# -*- coding: utf-8 -*-
"""测试专用：直接用内核会话密钥签发一个 cookie，不依赖明文口令。

仅本机测试工具使用（需要能读 config/session.key）。真实用户登录仍走
POST /api/login（PBKDF2 校验），口令不会出现在任何文件里。
"""

import os
import sys


def make_cookie(user="puppy"):
    platform = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if platform not in sys.path:
        sys.path.insert(0, platform)
    from kernel.auth import Auth
    auth = Auth(platform)
    return "kp_session=" + auth.issue(user)
