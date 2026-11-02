# -*- coding: utf-8 -*-
"""项目注册表：扫描 projects/，解析 manifest 继承链，实例化项目类，构建树。

manifest 继承（类似模板继承，声明式）：
    projects/<id>/project.json  "base": "coin"
    bases/coin.json             "base": "json-doc"  + 默认 acl/capabilities/view
    bases/json-doc.json         "base": "abstract"  + 协议版本
    最终 manifest = abstract ← json-doc ← coin ← 项目自身，后者覆盖前者。

类继承（代码层）：
    bases/<base>.json 的 "base" 字段同时决定 Python 基类：
        abstract -> AbstractProject
        json-doc -> JsonDocProject
        coin     -> CoinProject
    项目若提供 project.py，其 `Project` 必须是该基类的子类（内核强校验）。
"""

import importlib.util
import json
import os

from .bases.coin import CoinProject
from .project import AbstractProject, JsonDocProject

BASES = {
    "abstract": AbstractProject,
    "json-doc": JsonDocProject,
    "coin": CoinProject,
}


def deep_merge(base: dict, over: dict) -> dict:
    """manifest 合并：字典递归合并，标量/列表由子层覆盖。"""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Registry:
    def __init__(self, root: str, engine=None):
        self.root = root
        self.engine = engine
        self.projects = {}
        self.order = []
        self.errors = []
        self._load()

    # ---------------- manifest 继承链 ----------------
    def _base_manifest(self, key: str) -> dict:
        path = os.path.join(self.root, "bases", key + ".json")
        try:
            with open(path, encoding="utf-8") as f:
                spec = json.load(f)
        except Exception:
            spec = {"base": "abstract"}
        parent = spec.get("base")
        if parent and parent != key:
            spec = deep_merge(self._base_manifest(parent), spec)
        spec["base"] = key
        return spec

    @staticmethod
    def _import(name: str, path: str):
        mod_name = "kp_project_" + name.replace("-", "_")
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    # ---------------- 扫描与实例化 ----------------
    def _load(self):
        proj_root = os.path.join(self.root, "projects")
        if not os.path.isdir(proj_root):
            return
        for entry in sorted(os.scandir(proj_root), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            manifest_path = os.path.join(entry.path, "project.json")
            if not os.path.isfile(manifest_path):
                continue
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    own = json.load(f)
                own.setdefault("id", entry.name)
                base_key = own.get("base") or "json-doc"
                spec = self._base_manifest(base_key)
                spec = deep_merge(spec, own)
                spec["dir"] = entry.path
                spec.setdefault("view", {"kind": "auto"})

                base_cls = BASES.get(base_key, JsonDocProject)
                cls = base_cls
                py = os.path.join(entry.path, "project.py")
                if os.path.isfile(py):
                    mod = self._import(spec["id"], py)
                    candidate = getattr(mod, "Project", None)
                    if candidate is None:
                        raise ValueError("project.py 里没有 `Project = ...`")
                    if not issubclass(candidate, base_cls):
                        raise ValueError(
                            "project.py 的 Project 必须是 %s 的子类（manifest base=%r）"
                            % (base_cls.__name__, base_key))
                    cls = candidate

                data_dir = os.path.join(self.root, "data", spec["id"])
                os.makedirs(data_dir, exist_ok=True)
                self.projects[spec["id"]] = cls(spec, {
                    "role": None, "data_dir": data_dir, "engine": self.engine,
                })
                self.order.append(spec["id"])
            except Exception as e:  # 单个项目坏掉不影响整棵树
                self.errors.append("%s: %s" % (entry.name, e))

    # ---------------- 树 ----------------
    def get(self, pid: str):
        return self.projects.get(pid)

    def tree(self, session=None):
        children = {}
        for pid in self.order:
            spec = self.projects[pid].manifest()
            parent = spec.get("parent") or "root"
            children.setdefault(parent, []).append(spec)
        for v in children.values():
            v.sort(key=lambda s: (s.get("order", 100), s.get("id")))

        def node(spec):
            pid = spec["id"]
            return {
                "id": pid,
                "parent": spec.get("parent") or "root",
                "title": spec.get("title") or pid,
                "icon": spec.get("icon") or "📄",
                "order": spec.get("order", 100),
                "path": spec.get("path") or "",
                "hidden": bool(spec.get("hidden")),
                "capabilities": list(spec.get("capabilities") or []),
                "base": spec.get("base"),
                "desc": spec.get("desc") or "",
                "tags": list(spec.get("tags") or []),
                "roles": list(spec.get("roles") or []),
                "ui": spec.get("ui") or {},
                "view": {
                    "kind": (spec.get("view") or {}).get("kind", "auto"),
                    "url": (spec.get("view") or {}).get("url"),
                },
                "children": [node(c) for c in children.get(pid, [])],
            }

        root_spec = {}
        try:
            with open(os.path.join(self.root, "bases", "root.json"), encoding="utf-8") as f:
                root_spec = json.load(f)
        except Exception:
            pass
        root = {
            "id": "root",
            "title": root_spec.get("title") or "KittenPuppy4Ever",
            "icon": root_spec.get("icon") or "🐱🐶",
            "children": [node(c) for c in children.get("root", [])],
        }
        return {"root": root, "errors": self.errors}
