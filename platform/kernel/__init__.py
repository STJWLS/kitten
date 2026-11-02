# -*- coding: utf-8 -*-
"""KittenPuppy4Ever 平台内核。

对外只暴露三个概念：
    AbstractProject  抽象项目（协议）
    Registry         项目树（注册表）
    PlatformServer   根壳与统一路由
"""

from .project import AbstractProject, JsonDocProject
from .registry import Registry

__all__ = ["AbstractProject", "JsonDocProject", "Registry"]
