# -*- coding: utf-8 -*-
"""地点地图 module-local API：静态课程/地点投影。"""
import json
import os

from kernel.protocol import ProjectError

PREFIXES = ["/api/map/"]


def handle(handler, method, path, parsed):
    if method != "GET" or path != "/api/map/data":
        return False
    user = handler._require_user()
    if not handler._can_access(user, "map"):
        raise ProjectError("forbidden", "没有地图访问权限", 403)
    project = handler.registry.get("map")
    if not project:
        raise ProjectError("not_found", "地图项目不存在", 404)
    path_on_disk = os.path.join(project.manifest().get("dir") or "", "web", "schedule.json")
    try:
        with open(path_on_disk, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        raise ProjectError("not_found", "地图数据不存在", 404)
    handler._json(data)
    return True
