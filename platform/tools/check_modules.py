#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KittenPuppy4Ever 平台后端 module 只读校验器。

用法（推荐在 platform/ 根目录执行）::

    python tools/check_modules.py
    python tools/check_modules.py --json
    python tools/check_modules.py --root D:\\KittenPuppy4Ever\\platform --json

校验内容（与 platform/MODULE_SPEC.md 一一对应）::

    * projects/<dir>/project.json 是否存在、能否解析、是否为对象；
    * manifest 字段/类型、id 与目录名一致且唯一、path 以 / 开头且唯一；
    * parent 必须为 root 或已知 module id，parent 链不得成环；
    * base 必须在 bases/ 存在且在 kernel/registry.py 的 BASES 注册，继承链可解析；
    * capabilities 的元素/类型必须合法；值建议落在 base 继承链的词表内（内核不校验，
      偏离时记 WARN，见 MODULE_SPEC.md 的严重级别定义）；
    * path 若声明必须以 / 开头且唯一；缺失时记 WARN（registry 容忍、前端有 ?p=id 回退，
      但模块没有规范 URL，属规范偏离）；
    * view.kind 合法；custom view 必须有 web/index.html 且不能越出模块目录；
    * project.py 可选；若存在，其顶层 Project 必须按 manifest base 继承正确基类，
      且不得在 import 时执行网络/文件副作用（AST 静态启发式）。

本工具只读、只用标准库、不导入项目代码、不写文件、不启动服务、不访问网络。
退出码：0 = 全部 PASS（可能有 WARN）；1 = 存在硬性错误；2 = 参数/根目录错误。
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import sys

TOOL_VERSION = 1

VIEW_KINDS = ("auto", "custom", "legacy")
ACL_KEYS = ("read", "write")

MANIFEST_KNOWN_KEYS = {
    "id", "parent", "order", "title", "icon", "desc",
    "base", "capabilities", "acl", "ui", "view", "path",
    "tags", "roles", "hidden",
}
VIEW_KNOWN_KEYS = {"kind", "dir", "url"}

# kernel/registry.py BASES 里登记的基类 -> registry 的 issubclass 会接受的类集合
# （基类自身 + 它的所有已知子类）。超出该集合 registry 会拒绝加载。
PROJECT_CLASS_HIERARCHY = {
    "AbstractProject": {"AbstractProject", "JsonDocProject", "CoinProject"},
    "JsonDocProject": {"JsonDocProject", "CoinProject"},
    "CoinProject": {"CoinProject"},
}
KNOWN_CLASS_MODULES = {
    "kernel.project": {"AbstractProject", "JsonDocProject"},
    "kernel.bases.coin": {"CoinProject"},
}
FALLBACK_REGISTRY_BASES = {
    "abstract": "AbstractProject",
    "json-doc": "JsonDocProject",
    "coin": "CoinProject",
}

# import 期副作用静态启发式：明显触碰文件/网络/通知的调用点。
SIDE_EFFECT_TAIL_NAMES = {
    "open", "makedirs", "mkdir", "remove", "unlink", "rmdir", "removedirs",
    "rmtree", "rename", "write", "writelines", "write_text", "write_bytes",
    "touch", "chmod", "chown", "symlink", "link", "copyfile", "copytree",
    "move", "system", "popen", "check_call", "check_output", "urlopen",
    "urlretrieve", "connect", "sendall", "notify",
}
SIDE_EFFECT_DOTTED_MARKERS = (
    "socket", "requests", "urllib", "subprocess", "http.client", "shutil",
    "ftplib", "smtplib", "paramiko",
)

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
DATA_PROJECT_RE = re.compile(r"""data-project\s*=\s*["']([^"']+)["']""")
HEADER_TAG_RE = re.compile(r"<header[\s>]", re.IGNORECASE)
MAIN_PAGE_RE = re.compile(r"""<main\b[^>]*class\s*=\s*["'][^"']*\bpage\b""", re.IGNORECASE)
SECTION_TEMPLATE_RE = re.compile(r"""<section\b[^>]*class\s*=\s*["'][^"']*\bsection\b""", re.IGNORECASE)
H1_RE = re.compile(r"<h1[\s>]", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def issue(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def read_json(path: str):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def read_text(path: str, limit: int = 1024 * 1024) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read(limit)


def deep_merge(base: dict, over: dict) -> dict:
    """与 kernel/registry.py 的 deep_merge 完全一致：字典递归，标量/列表覆盖。"""
    out = dict(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def is_within(root: str, path: str) -> bool:
    root_abs = os.path.abspath(root)
    path_abs = os.path.abspath(path)
    return path_abs == root_abs or path_abs.startswith(root_abs + os.sep)


def dotted_name(node: ast.AST):
    """把 a.b.c / a 形式的表达式还原成点分字符串，其它形式返回 None。"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def is_main_guard(node: ast.AST) -> bool:
    if not isinstance(node, ast.Compare):
        return False
    if not (isinstance(node.left, ast.Name) and node.left.id == "__name__"):
        return False
    if not (len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)):
        return False
    return (
        len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value == "__main__"
    )


def looks_like_side_effect(dotted: str) -> bool:
    if not dotted:
        return False
    if dotted.rsplit(".", 1)[-1] in SIDE_EFFECT_TAIL_NAMES:
        return True
    return any(marker in dotted for marker in SIDE_EFFECT_DOTTED_MARKERS)


# ---------------------------------------------------------------------------
# bases 继承链（读 bases/*.json + 静态解析 kernel/registry.py 的 BASES）
# ---------------------------------------------------------------------------

def read_registry_bases(platform_root: str):
    """从 kernel/registry.py 静态解析 BASES 映射；返回 (mapping, 错误说明)。"""
    path = os.path.join(platform_root, "kernel", "registry.py")
    try:
        text = read_text(path, 4 * 1024 * 1024)
    except OSError as exc:
        return None, "无法读取 kernel/registry.py：%s" % exc
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return None, "kernel/registry.py 语法错误：%s" % exc
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        has_target = any(isinstance(t, ast.Name) and t.id == "BASES" for t in node.targets)
        if not has_target or not isinstance(node.value, ast.Dict):
            continue
        mapping = {}
        for key_node, value_node in zip(node.value.keys, node.value.values):
            if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
                continue
            class_name = None
            if isinstance(value_node, ast.Name):
                class_name = value_node.id
            elif isinstance(value_node, ast.Attribute):
                class_name = value_node.attr
            if class_name:
                mapping[key_node.value] = class_name
        if mapping:
            return mapping, None
    return None, "kernel/registry.py 中没有找到 BASES = {...} 映射"


class BasesContext:
    """bases 目录与继承链的只读视图。"""

    def __init__(self, platform_root: str):
        self.root = platform_root
        self.bases_dir = os.path.join(platform_root, "bases")
        self.files = {}          # base 名 -> manifest dict
        self.registered = {}     # base 名 -> Python 类名
        self.chains = {}         # base 名 -> [自身, 父, ...]
        self.errors = []
        self.warnings = []
        self._resolved = {}
        self._load()

    # -- 加载与全局校验 ---------------------------------------------------
    def _load(self):
        if not os.path.isdir(self.bases_dir):
            self.errors.append(issue("E_BASES_DIR", "bases/ 目录不存在：%s" % self.bases_dir))
            return

        registry, registry_problem = read_registry_bases(self.root)
        if registry is None:
            self.warnings.append(issue(
                "W_REGISTRY_BASES_FALLBACK",
                "%s；改用内置映射 %s（若 registry.py 结构变化，请同步本工具）"
                % (registry_problem, FALLBACK_REGISTRY_BASES)))
            registry = dict(FALLBACK_REGISTRY_BASES)
        self.registered = registry

        for filename in sorted(os.listdir(self.bases_dir)):
            if not filename.endswith(".json"):
                continue
            name = filename[:-5]
            path = os.path.join(self.bases_dir, filename)
            try:
                manifest = read_json(path)
            except Exception as exc:  # noqa: BLE001 - 报告任何解析失败
                self.errors.append(issue("E_BASE_JSON", "bases/%s 解析失败：%s" % (filename, exc)))
                continue
            if not isinstance(manifest, dict):
                self.errors.append(issue("E_BASE_JSON", "bases/%s 顶层必须是 JSON 对象" % filename))
                continue
            self.files[name] = manifest

        for name in sorted(self.registered):
            if name not in self.files:
                self.errors.append(issue(
                    "E_BASE_REGISTERED_NO_FILE",
                    "kernel/registry.py BASES 注册了 %r，但 bases/%s.json 不存在" % (name, name)))

        for name in sorted(self.files):
            if name == "root":
                continue  # bases/root.json 只是根节点元信息，不是项目基类
            if name not in self.registered:
                self.warnings.append(issue(
                    "W_BASE_UNREGISTERED",
                    "bases/%s.json 未在 kernel/registry.py 的 BASES 注册，项目无法安全使用该 base"
                    % name))
            self._validate_base_manifest(name, self.files[name])

        for name in sorted(self.files):
            if name == "root":
                continue
            chain, problem = self._chain(name)
            self.chains[name] = chain
            if problem:
                if name in self.registered:
                    self.errors.append(issue(
                        "E_BASE_CHAIN", "bases/%s.json 继承链无法解析：%s" % (name, problem)))
                continue
            if name in self.registered:
                for member in chain:
                    if member not in self.registered:
                        self.errors.append(issue(
                            "E_BASE_CHAIN_UNREGISTERED",
                            "base %r 的继承链引用了未注册的 %r（registry.BASES 中没有）"
                            % (name, member)))

    def _validate_base_manifest(self, name: str, manifest: dict):
        raw_base = manifest.get("base")
        if raw_base is not None and not isinstance(raw_base, str):
            self.errors.append(issue(
                "E_BASE_FIELD_TYPE", "bases/%s.json 的 base 必须是字符串" % name))
        caps = manifest.get("capabilities")
        if caps is not None:
            if not isinstance(caps, list):
                self.errors.append(issue(
                    "E_BASE_CAPS_TYPE", "bases/%s.json 的 capabilities 必须是字符串数组" % name))
            else:
                for cap in caps:
                    if not isinstance(cap, str) or not cap.strip():
                        self.errors.append(issue(
                            "E_BASE_CAPS_ITEM",
                            "bases/%s.json 的 capabilities 含非字符串/空项：%r" % (name, cap)))
        acl = manifest.get("acl")
        if acl is not None:
            if not isinstance(acl, dict):
                self.errors.append(issue("E_BASE_ACL_TYPE", "bases/%s.json 的 acl 必须是对象" % name))
            else:
                for side in ACL_KEYS:
                    if side in acl and not isinstance(acl[side], list):
                        self.errors.append(issue(
                            "E_BASE_ACL_SIDE", "bases/%s.json 的 acl.%s 必须是数组" % (name, side)))
        view = manifest.get("view")
        if view is not None and not isinstance(view, dict):
            self.errors.append(issue("E_BASE_VIEW_TYPE", "bases/%s.json 的 view 必须是对象" % name))

    def _chain(self, name: str):
        seen = []
        current = name
        while True:
            if current not in self.files:
                return seen, "继承目标 bases/%s.json 不存在" % current
            if current in seen:
                return seen, "继承链存在环：%s" % " -> ".join(seen + [current])
            seen.append(current)
            parent = self.files[current].get("base")
            if parent is None or parent == "" or parent == current:
                return seen, None
            if not isinstance(parent, str):
                return seen, "bases/%s.json 的 base 不是字符串" % current
            current = parent

    # -- 供 module 检查使用 -------------------------------------------------
    def resolved(self, name: str) -> dict:
        return self._resolved_impl(name, ())

    def _resolved_impl(self, name: str, stack: tuple) -> dict:
        if name in self._resolved:
            return self._resolved[name]
        if name in stack:
            raise ValueError("继承链存在环：%s" % " -> ".join(stack + (name,)))
        manifest = self.files.get(name)
        if manifest is None:
            raise ValueError("bases/%s.json 不存在" % name)
        spec = dict(manifest)
        parent = spec.get("base")
        if isinstance(parent, str) and parent and parent != name:
            spec = deep_merge(self._resolved_impl(parent, stack + (name,)), spec)
        spec["base"] = name
        self._resolved[name] = spec
        return spec

    def allowed_capabilities(self, name: str):
        """base 继承链上出现过的 capability 并集（None 表示链不可用）。"""
        chain = self.chains.get(name)
        if not chain:
            return None
        allowed = []
        for member in chain:
            caps = self.files.get(member, {}).get("capabilities")
            if isinstance(caps, list):
                for cap in caps:
                    if isinstance(cap, str) and cap not in allowed:
                        allowed.append(cap)
        return allowed


# ---------------------------------------------------------------------------
# project.py 静态检查
# ---------------------------------------------------------------------------

class ProjectPyChecker:
    def __init__(self, base_key, base_class, errors, warnings):
        self.base_key = base_key
        self.base_class = base_class
        self.errors = errors
        self.warnings = warnings

    def check(self, path: str):
        try:
            text = read_text(path, 2 * 1024 * 1024)
        except OSError as exc:
            self.errors.append(issue("E_PY_READ", "project.py 读取失败：%s" % exc))
            return
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as exc:
            self.errors.append(issue(
                "E_PY_SYNTAX", "project.py 语法错误（registry 导入会失败）：%s" % exc))
            return

        imported, module_aliases = self._collect_imports(tree)
        local_classes = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                local_classes[node.name] = list(node.bases)

        project_class = None
        project_assign = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Project":
                project_class = node
                break
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id == "Project" for t in targets):
                    project_assign = node
                    break

        if project_class is None and project_assign is None:
            self.errors.append(issue(
                "E_PY_NO_PROJECT",
                "project.py 里没有顶层 `Project` 类或 `Project = ...` 赋值（registry 会抛 ValueError）"))
            self._check_import_side_effects(tree)
            return

        resolved_class = None
        if project_class is not None:
            if not project_class.bases:
                self.errors.append(issue(
                    "E_PY_NO_BASE", "project.py 的 Project 没有继承任何基类（registry 的 issubclass 校验会失败）"))
            else:
                for base_expr in project_class.bases:
                    resolved_class = self._resolve(base_expr, imported, module_aliases, local_classes)
                    if resolved_class:
                        break
                if resolved_class is None:
                    self.errors.append(issue(
                        "E_PY_PROJECT_UNRESOLVED",
                        "无法静态确认 Project 的基类（第 %d 行）；请直接从 kernel.project / "
                        "kernel.bases.coin 导入 AbstractProject/JsonDocProject/CoinProject"
                        % project_class.lineno))
            self._check_base_attr(project_class)
        else:
            value = project_assign.value
            resolved_class = self._resolve(value, imported, module_aliases, local_classes)
            if resolved_class is None:
                self.errors.append(issue(
                    "E_PY_PROJECT_UNRESOLVED",
                    "无法静态确认 `Project = ...` 指向的基类（第 %d 行）" % project_assign.lineno))
            else:
                self.warnings.append(issue(
                    "W_PY_PROJECT_ALIAS",
                    "Project 是类别名赋值而非 class 定义；registry 接受，但建议写成 "
                    "`class Project(...)` 便于阅读"))

        if resolved_class and self.base_class:
            allowed = PROJECT_CLASS_HIERARCHY.get(self.base_class, {self.base_class})
            if resolved_class not in allowed:
                self.errors.append(issue(
                    "E_PY_BASE_MISMATCH",
                    "Project 继承 %s，但 manifest base=%r 要求 %s 的子类（registry 会拒绝加载）"
                    % (resolved_class, self.base_key, self.base_class)))
            elif resolved_class != self.base_class:
                self.warnings.append(issue(
                    "W_PY_BASE_LOOSER",
                    "Project 继承 %s，比 manifest base=%r 声明的 %s 更宽；"
                    "确认 manifest 的 base/capabilities 是否需要同步"
                    % (resolved_class, self.base_key, self.base_class)))

        self._check_import_side_effects(tree)

    # -- 解析辅助 ---------------------------------------------------------
    @staticmethod
    def _collect_imports(tree):
        imported = {}
        module_aliases = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    local = alias.asname or alias.name
                    if module in KNOWN_CLASS_MODULES and alias.name in KNOWN_CLASS_MODULES[module]:
                        imported[local] = alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        module_aliases[alias.asname] = alias.name
                    else:
                        top = alias.name.split(".")[0]
                        module_aliases.setdefault(top, top)
        return imported, module_aliases

    @classmethod
    def _resolve(cls, node, imported, module_aliases, local_classes, seen=()):
        if isinstance(node, ast.Name):
            if node.id in imported:
                return imported[node.id]
            if node.id in local_classes:
                if node.id in seen:
                    return None
                for base_expr in local_classes[node.id]:
                    resolved = cls._resolve(
                        base_expr, imported, module_aliases, local_classes, seen + (node.id,))
                    if resolved:
                        return resolved
            return None
        if isinstance(node, ast.Attribute):
            dotted = dotted_name(node)
            if not dotted:
                return None
            parts = dotted.split(".")
            if parts[0] in module_aliases:
                head = module_aliases[parts[0]]
                dotted = head + ("." + ".".join(parts[1:]) if len(parts) > 1 else "")
            module, _, attr = dotted.rpartition(".")
            if module in KNOWN_CLASS_MODULES and attr in KNOWN_CLASS_MODULES[module]:
                return attr
        return None

    def _check_base_attr(self, project_class: ast.ClassDef):
        declared = None
        found = False
        for stmt in project_class.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                if any(isinstance(t, ast.Name) and t.id == "base" for t in targets):
                    found = True
                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        declared = stmt.value.value
        if not found:
            self.warnings.append(issue(
                "W_PY_BASE_ATTR",
                "Project 未声明 `base = ...` 类属性（registry 不读取，但建议与 manifest 保持一致）"))
        elif declared is not None and self.base_key and declared != self.base_key:
            self.warnings.append(issue(
                "W_PY_BASE_ATTR_MISMATCH",
                "Project.base=%r 与 manifest base=%r 不一致" % (declared, self.base_key)))

    # -- import 期副作用 ---------------------------------------------------
    def _check_import_side_effects(self, tree: ast.Module):
        calls = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):  # noqa: N802 - ast API
                self._visit_signature(node)

            def visit_AsyncFunctionDef(self, node):  # noqa: N802
                self._visit_signature(node)

            def _visit_signature(self, node):
                for decorator in node.decorator_list:
                    self.visit(decorator)
                args = node.args
                for default in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
                    self.visit(default)

            def visit_ClassDef(self, node):  # noqa: N802
                for decorator in node.decorator_list:
                    self.visit(decorator)
                for base_expr in node.bases:
                    self.visit(base_expr)
                for keyword in node.keywords:
                    self.visit(keyword)
                for stmt in node.body:
                    self.visit(stmt)

            def visit_Lambda(self, node):  # noqa: N802
                return  # lambda 体不在 import 时执行

            def visit_If(self, node):  # noqa: N802
                if is_main_guard(node.test):
                    return  # __main__ 受保护代码不会在 import 时执行
                self.generic_visit(node)

            def visit_Call(self, node):  # noqa: N802
                calls.append(node)
                self.generic_visit(node)

        Visitor().visit(tree)
        for call in calls:
            dotted = dotted_name(call.func)
            if dotted and looks_like_side_effect(dotted):
                self.errors.append(issue(
                    "E_PY_IMPORT_SIDE_EFFECT",
                    "project.py 第 %d 行在 import 时执行可疑副作用调用 %s()；"
                    "规范要求 import 无网络/文件副作用（registry 会 exec_module）"
                    % (call.lineno, dotted)))


# ---------------------------------------------------------------------------
# 单个 module 检查
# ---------------------------------------------------------------------------

def find_cycles(parent_map: dict):
    """返回 {module_id: 'a -> b -> a'}，只标记真正落在环里的节点。"""
    state = {}   # 0/未访问=缺省, 1=栈中, 2=完成
    cycles = {}
    for start in sorted(parent_map):
        if start == "root" or state.get(start) == 2:
            continue
        stack = []
        index = {}
        current = start
        while current and current != "root":
            if state.get(current) == 2:
                break
            if current in index:
                cycle_nodes = stack[index[current]:]
                text = " -> ".join(cycle_nodes + [current])
                for member in cycle_nodes:
                    cycles.setdefault(member, text)
                break
            index[current] = len(stack)
            stack.append(current)
            nxt = parent_map.get(current)
            current = nxt if isinstance(nxt, str) and nxt else "root"
        for member in stack:
            state[member] = 2
    return cycles


class ModuleChecker:
    def __init__(self, platform_root: str):
        self.root = platform_root
        self.bases = BasesContext(platform_root)
        self.global_errors = []
        self.global_warnings = []
        self.modules = []

    # -- 主流程 ------------------------------------------------------------
    def run(self):
        projects_dir = os.path.join(self.root, "projects")
        if not os.path.isdir(projects_dir):
            self.global_errors.append(issue("E_PROJECTS_DIR", "projects/ 目录不存在：%s" % projects_dir))
            return self._report()
        if not os.path.isfile(os.path.join(self.root, "kernel", "registry.py")):
            self.global_errors.append(issue(
                "E_REGISTRY_MISSING", "kernel/registry.py 不存在，无法确认 base 与类继承规则"))

        entries = sorted(os.scandir(projects_dir), key=lambda e: e.name)
        raw = []  # (dir_name, dir_path, doc)
        for entry in entries:
            if not entry.is_dir():
                self.global_warnings.append(issue(
                    "W_PROJECTS_STRAY_FILE", "projects/ 下存在非目录条目 %r，registry 会忽略" % entry.name))
                continue
            manifest_path = os.path.join(entry.path, "project.json")
            if not os.path.isfile(manifest_path):
                self.modules.append(self._failure(
                    entry.name, "E_MANIFEST_MISSING",
                    "projects/%s/project.json 不存在；registry 会静默跳过该目录" % entry.name))
                continue
            try:
                doc = read_json(manifest_path)
            except Exception as exc:  # noqa: BLE001 - 任何 JSON 错误都要报告
                self.modules.append(self._failure(
                    entry.name, "E_MANIFEST_JSON",
                    "projects/%s/project.json 解析失败：%s" % (entry.name, exc)))
                continue
            if not isinstance(doc, dict):
                self.modules.append(self._failure(
                    entry.name, "E_MANIFEST_TYPE",
                    "projects/%s/project.json 顶层必须是 JSON 对象" % entry.name))
                continue
            raw.append((entry.name, entry.path, doc))

        # 先算 effective id，再做全局唯一性 / parent / path 检查
        effective_ids = {}
        for dir_name, _dir_path, doc in raw:
            raw_id = doc.get("id")
            effective_ids[dir_name] = raw_id if isinstance(raw_id, str) and raw_id else dir_name
        id_map = {}
        for dir_name, _dir_path, doc in raw:
            id_map.setdefault(effective_ids[dir_name], []).append(dir_name)
        dup_ids = {key: value for key, value in id_map.items() if len(value) > 1}
        known_ids = set(id_map) | {"root"}

        path_map = {}
        for dir_name, _dir_path, doc in raw:
            path = doc.get("path")
            if isinstance(path, str) and path:
                path_map.setdefault(path, []).append(effective_ids[dir_name])
        dup_paths = {key: value for key, value in path_map.items() if len(value) > 1}

        parent_map = {}
        for dir_name, _dir_path, doc in raw:
            parent = doc.get("parent")
            parent_map[effective_ids[dir_name]] = parent if isinstance(parent, str) and parent else "root"
        cycles = find_cycles(parent_map)

        for dir_name, dir_path, doc in raw:
            self.modules.append(self._inspect(
                dir_name, dir_path, doc, effective_ids[dir_name], known_ids,
                dup_ids, dup_paths, cycles))

        self.modules.sort(key=lambda item: item["dir"])
        return self._report()

    # -- 结果构造 ----------------------------------------------------------
    def _failure(self, dir_name: str, code: str, message: str):
        return {
            "dir": "projects/" + dir_name,
            "id": dir_name,
            "status": "FAIL",
            "errors": [issue(code, message)],
            "warnings": [],
            "effective": {
                "id": dir_name, "parent": "root", "base": None,
                "view_kind": None, "view_dir": None, "path": "", "capabilities": [],
            },
        }

    def _report(self):
        module_errors = sum(len(item["errors"]) for item in self.modules)
        module_warnings = sum(len(item["warnings"]) for item in self.modules)
        pass_count = sum(1 for item in self.modules if item["status"] == "PASS")
        fail_count = len(self.modules) - pass_count
        bases = {
            "registered": dict(sorted(self.bases.registered.items())),
            "files": sorted(self.bases.files),
            "chains": {key: self.bases.chains.get(key, []) for key in sorted(self.bases.files)},
            "errors": self.bases.errors,
            "warnings": self.bases.warnings,
        }
        error_total = module_errors + len(self.bases.errors) + len(self.global_errors)
        warning_total = module_warnings + len(self.bases.warnings) + len(self.global_warnings)
        return {
            "tool": "check_modules.py",
            "version": TOOL_VERSION,
            "platform_root": self.root,
            "ok": error_total == 0,
            "bases": bases,
            "global": {
                "errors": self.global_errors,
                "warnings": self.global_warnings,
            },
            "modules": self.modules,
            "summary": {
                "modules": len(self.modules),
                "pass": pass_count,
                "fail": fail_count,
                "errors": error_total,
                "warnings": warning_total,
                "module_errors": module_errors,
                "module_warnings": module_warnings,
                "base_errors": len(self.bases.errors),
                "base_warnings": len(self.bases.warnings),
                "global_errors": len(self.global_errors),
                "global_warnings": len(self.global_warnings),
            },
        }

    # -- 单个 module 的字段检查 --------------------------------------------
    def _inspect(self, dir_name, module_dir, doc, effective_id, known_ids,
                 dup_ids, dup_paths, cycles):
        errors = []
        warnings = []

        def E(code, message):
            errors.append(issue(code, message))

        def W(code, message):
            warnings.append(issue(code, message))

        # 未知顶层键（registry 不读取，可能是拼写错误）
        for key in sorted(doc):
            if key not in MANIFEST_KNOWN_KEYS:
                W("W_UNKNOWN_FIELD", "manifest 顶层键 %r 不会被 registry 读取（可能是拼写错误）" % key)
        if "dir" in doc:
            W("W_RESERVED_DIR", "manifest 的 dir 键会被 registry 用实际目录覆盖，应删除")

        # id ---------------------------------------------------------------
        raw_id = doc.get("id")
        if raw_id is None:
            W("W_ID_DEFAULTED",
              "未声明 id；registry 默认使用目录名 %r（行为正确，建议显式写出）" % dir_name)
        elif not isinstance(raw_id, str) or not raw_id:
            E("E_ID_TYPE", "id 必须是非空字符串")
        elif effective_id != dir_name:
            E("E_ID_MISMATCH",
              "manifest id=%r 与目录名 %r 不一致；registry 会按 id 注册，"
              "导致 /p/%s/ 与数据目录 data/%s 和目录名脱节"
              % (effective_id, dir_name, effective_id, effective_id))
        if effective_id == "root":
            E("E_ID_RESERVED", "module id 不能是 'root'（与根节点冲突）")
        if not ID_PATTERN.match(effective_id):
            E("E_ID_PATTERN",
              "id=%r 含 /p/ 路由不支持字符；server.py 的 VIEW_RE 只匹配 [A-Za-z0-9_-]+"
              % effective_id)
        if len(dup_ids.get(effective_id, [])) > 1:
            E("E_ID_DUPLICATE",
              "id=%r 被多个目录使用：%s（registry 字典会静默覆盖）"
              % (effective_id, ", ".join(sorted(dup_ids[effective_id]))))

        # parent -----------------------------------------------------------
        parent = "root"
        raw_parent = doc.get("parent")
        if raw_parent is None:
            W("W_PARENT_DEFAULTED", "未声明 parent；registry 默认挂到 root（行为正确，建议显式写出）")
        elif not isinstance(raw_parent, str) or not raw_parent:
            E("E_PARENT_TYPE", "parent 必须是非空字符串")
        else:
            parent = raw_parent
            if parent != "root" and parent not in known_ids:
                E("E_PARENT_UNKNOWN",
                  "parent=%r 不存在；必须为 root 或已知 module id（否则树里挂空，模块不可见）"
                  % parent)
            if parent == effective_id:
                E("E_PARENT_SELF", "parent 不能指向自己")
            elif effective_id in cycles:
                E("E_PARENT_CYCLE", "parent 链存在环：%s" % cycles[effective_id])

        # 元信息 -----------------------------------------------------------
        for key, note in (
            ("title", "registry 会回退为 id"),
            ("icon", "registry 会回退为默认图标"),
            ("desc", "registry 会回退为空字符串"),
        ):
            if key not in doc or doc.get(key) is None:
                W("W_FIELD_DEFAULTED", "%s 未声明；%s（建议显式写出）" % (key, note))
            elif not isinstance(doc[key], str):
                E("E_FIELD_TYPE", "%s 必须是字符串" % key)
            elif key in ("title", "icon") and not doc[key].strip():
                W("W_FIELD_EMPTY", "%s 是空字符串；registry 会回退默认值" % key)

        # order ------------------------------------------------------------
        if "order" in doc and doc["order"] is not None:
            value = doc["order"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                E("E_ORDER_TYPE", "order 必须是数字（registry 用来排序，默认 100）")
            elif isinstance(value, float) and not math.isfinite(value):
                E("E_ORDER_TYPE", "order 必须是有限数字")
        else:
            W("W_ORDER_DEFAULTED", "未声明 order；registry 默认 100（建议显式写出）")

        # hidden / tags / roles / acl / ui ---------------------------------
        if "hidden" in doc and not isinstance(doc["hidden"], bool):
            E("E_HIDDEN_TYPE", "hidden 必须是布尔值")
        for key in ("tags", "roles"):
            if key in doc:
                value = doc[key]
                if not isinstance(value, list):
                    E("E_%s_TYPE" % key.upper(), "%s 必须是字符串数组" % key)
                else:
                    for item in value:
                        if not isinstance(item, str) or not item.strip():
                            E("E_%s_ITEM" % key.upper(),
                              "%s 含非字符串/空项：%r" % (key, item))
        if "acl" in doc:
            acl = doc["acl"]
            if not isinstance(acl, dict):
                E("E_ACL_TYPE", "acl 必须是对象，如 {\"read\": [...], \"write\": [...]}")
            else:
                for side in sorted(acl):
                    if side not in ACL_KEYS:
                        W("W_ACL_UNKNOWN_KEY",
                          "acl 键 %r 不会被 registry 使用（只读取 read/write）" % side)
                    elif not isinstance(acl[side], list) or not all(
                            isinstance(role, str) and role.strip() for role in acl[side]):
                        E("E_ACL_SIDE", "acl.%s 必须是字符串数组（空数组表示对所有角色开放）" % side)
        if "ui" in doc:
            ui = doc["ui"]
            if not isinstance(ui, dict):
                E("E_UI_TYPE", "ui 必须是对象")
            else:
                theme = ui.get("theme")
                if theme is not None:
                    if not isinstance(theme, dict):
                        E("E_UI_THEME_TYPE", "ui.theme 必须是对象")
                    elif "accent" in theme and not isinstance(theme["accent"], str):
                        E("E_UI_ACCENT_TYPE", "ui.theme.accent 必须是字符串")

        # base -------------------------------------------------------------
        base_key = None
        base_manifest = None
        raw_base = doc.get("base")
        if raw_base is None:
            base_key = "json-doc"
            W("W_BASE_DEFAULTED",
              "未声明 base；registry 默认按 json-doc 继承（缺省可继承，不是违规；建议显式写出）")
        elif not isinstance(raw_base, str) or not raw_base:
            E("E_BASE_TYPE", "base 必须是非空字符串")
        else:
            base_key = raw_base
            if base_key not in self.bases.files:
                E("E_BASE_MISSING", "base=%r 没有对应的 bases/%s.json" % (base_key, base_key))
                base_key = None
            elif base_key not in self.bases.registered:
                E("E_BASE_UNREGISTERED",
                  "base=%r 未在 kernel/registry.py 的 BASES 注册；"
                  "registry 会静默回退到 JsonDocProject，声明与实际不一致" % base_key)
                base_key = None
        if base_key:
            try:
                base_manifest = self.bases.resolved(base_key)
            except ValueError as exc:
                E("E_BASE_CHAIN", "base=%r 继承链无法解析：%s" % (base_key, exc))
                base_key = None

        # capabilities -----------------------------------------------------
        allowed_caps = self.bases.allowed_capabilities(base_key) if base_key else None
        effective_caps = []
        raw_caps = doc.get("capabilities")
        if raw_caps is None:
            if base_manifest is not None:
                inherited = base_manifest.get("capabilities")
                effective_caps = list(inherited) if isinstance(inherited, list) else []
                W("W_CAPS_INHERITED",
                  "未声明 capabilities；继承 base %r -> %s（缺省可继承，不是违规；"
                  "建议显式写出实际使用的能力）" % (base_key, effective_caps))
            else:
                W("W_CAPS_INHERITED",
                  "未声明 capabilities；因 base 无效无法计算继承集合（缺省可继承，不是违规）")
        elif not isinstance(raw_caps, list):
            E("E_CAPS_TYPE", "capabilities 必须是字符串数组")
        else:
            effective_caps = list(raw_caps)
            caps_ok = True
            for cap in raw_caps:
                if not isinstance(cap, str) or not cap.strip():
                    E("E_CAPS_ITEM", "capabilities 含非字符串/空项：%r" % (cap,))
                    caps_ok = False
            if caps_ok and allowed_caps is not None:
                unknown = [cap for cap in raw_caps if cap not in allowed_caps]
                if unknown:
                    W("W_CAP_UNKNOWN",
                      "capabilities 中的 %s 不在 base %r 的继承词表内（词表：%s）。"
                      "kernel/registry.py 与 server.py 都不校验 capability 值，因此这不是"
                      "加载错误；但 capabilities 是 module 的协议声明，建议改为已定义能力，"
                      "或先在 bases/*.json 与本规范里增加该能力"
                      % (unknown, base_key, allowed_caps))

        # view -------------------------------------------------------------
        view_kind = "auto"
        view_dir = None
        raw_view = doc.get("view")
        if raw_view is None:
            W("W_VIEW_DEFAULTED",
              "未声明 view；registry 默认 {kind: auto}，由内核生成通用 CRUD 视图"
              "（缺省可用，不是违规）")
        elif not isinstance(raw_view, dict):
            E("E_VIEW_TYPE", "view 必须是对象")
        else:
            for key in sorted(raw_view):
                if key not in VIEW_KNOWN_KEYS:
                    W("W_VIEW_UNKNOWN_KEY",
                      "view.%s 不会被 registry 使用（只读取 kind/dir/url）" % key)
            kind = raw_view.get("kind")
            if kind is None:
                W("W_VIEW_KIND_DEFAULTED", "view 未声明 kind；registry 按 auto 处理")
            elif not isinstance(kind, str):
                E("E_VIEW_KIND_TYPE", "view.kind 必须是字符串")
            elif kind not in VIEW_KINDS:
                E("E_VIEW_KIND_INVALID",
                  "view.kind=%r 不合法（可选：auto/custom/legacy）；registry 会静默按 auto 处理"
                  % kind)
            else:
                view_kind = kind

            if view_kind == "custom":
                dir_rel = raw_view.get("dir")
                if dir_rel is None:
                    W("W_VIEW_DIR_DEFAULTED", "custom view 未声明 dir；registry 默认使用 web")
                    dir_rel = "web"
                elif not isinstance(dir_rel, str) or not dir_rel.strip():
                    E("E_VIEW_DIR_TYPE", "custom view 的 dir 必须是非空字符串")
                    dir_rel = None
                if dir_rel:
                    view_dir = dir_rel
                    target = os.path.normpath(os.path.join(module_dir, dir_rel))
                    if not is_within(module_dir, target):
                        E("E_VIEW_DIR_ESCAPE",
                          "view.dir=%r 越出模块目录（_serve_static 会 403）" % dir_rel)
                    elif not os.path.isdir(target):
                        E("E_VIEW_DIR_MISSING",
                          "custom view 目录不存在：projects/%s/%s" % (dir_name, dir_rel))
                    else:
                        index_path = os.path.join(target, "index.html")
                        if not os.path.isfile(index_path):
                            E("E_VIEW_INDEX_MISSING",
                              "custom view 缺少 index.html：projects/%s/%s/index.html"
                              % (dir_name, dir_rel))
                        else:
                            self._check_template(effective_id, index_path, errors, warnings)
                if "url" in raw_view:
                    W("W_VIEW_URL_UNUSED", "custom view 不使用 url 键")
            elif view_kind == "legacy":
                url = raw_view.get("url")
                if url is None:
                    W("W_LEGACY_URL_DEFAULTED", "legacy view 未声明 url；registry 默认 /legacy/")
                elif not isinstance(url, str):
                    E("E_LEGACY_URL_TYPE", "legacy view 的 url 必须是字符串")
                elif not url.startswith("/"):
                    W("W_LEGACY_URL_SLASH",
                      "legacy view 的 url 建议以 / 开头（registry 会原样 302）")
                if "dir" in raw_view:
                    W("W_VIEW_DIR_UNUSED", "legacy view 不使用 dir 键")
            else:  # auto
                if os.path.isfile(os.path.join(module_dir, "web", "index.html")):
                    W("W_AUTO_VIEW_UNUSED_WEB",
                      "view.kind=auto 不使用 web/；web/index.html 不会被渲染，"
                      "若这是自定义页面应改为 custom")

        # path -------------------------------------------------------------
        path_value = ""
        raw_path = doc.get("path")
        if raw_path is None:
            W("W_PATH_MISSING",
              "未声明 path；registry 会给空字符串。模块仍会出现在首页卡片"
              "（static/index.html 的 renderHome 只过滤 hidden，不看 path），点击时走 "
              "navigate() 的 /home?p=%s 回退打开，也能直接访问 /p/%s/；"
              "但没有规范 URL/深链，server 的 canonical_paths 不收录，"
              "作为子页面时也不显示 chip。规范要求常规可导航 module 声明 path，"
              "故记 WARN（不是加载错误）；若刻意省略，应同时 hidden:true 并在规范里登记例外"
              % (effective_id, effective_id))
        elif not isinstance(raw_path, str):
            E("E_PATH_TYPE", "path 必须是字符串")
        elif not raw_path.startswith("/"):
            E("E_PATH_SLASH", "path=%r 必须以 / 开头" % raw_path)
        else:
            path_value = raw_path
            if not raw_path.endswith("/"):
                W("W_PATH_TRAILING_SLASH", "path 建议以 / 结尾（现有模块均如此）")
            if raw_path.strip() != raw_path:
                W("W_PATH_WHITESPACE", "path 首尾含空白字符")
            same_path = dup_paths.get(raw_path)
            if same_path and len(same_path) > 1:
                E("E_PATH_DUPLICATE",
                  "path=%r 被多个模块使用：%s（前端路由/旧 URL 会互相覆盖）"
                  % (raw_path, ", ".join(sorted(same_path))))

        # project.py -------------------------------------------------------
        py_path = os.path.join(module_dir, "project.py")
        if os.path.isfile(py_path):
            base_class = self.bases.registered.get(base_key) if base_key else None
            ProjectPyChecker(base_key, base_class, errors, warnings).check(py_path)

        status = "PASS" if not errors else "FAIL"
        return {
            "dir": "projects/" + dir_name,
            "id": effective_id,
            "status": status,
            "errors": errors,
            "warnings": warnings,
            "effective": {
                "id": effective_id,
                "parent": parent,
                "base": base_key,
                "view_kind": view_kind,
                "view_dir": view_dir,
                "path": path_value,
                "capabilities": effective_caps,
            },
        }

    # -- TEMPLATE.md 的轻量静态检查（建议项） -------------------------------
    @staticmethod
    def _check_template(module_id, index_path, errors, warnings):
        try:
            text = read_text(index_path, 512 * 1024)
        except OSError as exc:
            errors.append(issue("E_VIEW_INDEX_READ", "custom view index.html 读取失败：%s" % exc))
            return
        if not text.strip():
            errors.append(issue("E_VIEW_INDEX_EMPTY", "custom view index.html 是空文件"))
            return
        if "/static/template.css" not in text:
            warnings.append(issue(
                "W_TEMPLATE_CSS",
                "custom 页面未引用 /static/template.css（TEMPLATE.md 要求所有页面使用统一模板）"))
        match = DATA_PROJECT_RE.search(text)
        if not match:
            warnings.append(issue(
                "W_TEMPLATE_PROJECT_ATTR",
                "custom 页面缺少 <body data-project=\"<id>\">（TEMPLATE.md 页面骨架）"))
        elif match.group(1) != module_id:
            warnings.append(issue(
                "W_TEMPLATE_PROJECT_ATTR",
                "页面 body data-project=%r 与 module id=%r 不一致" % (match.group(1), module_id)))
        if HEADER_TAG_RE.search(text):
            warnings.append(issue(
                "W_TEMPLATE_HEADER",
                "custom 页面出现 <header>；页头/返回/登录门禁应由根壳统一提供（TEMPLATE.md）"))
        if not MAIN_PAGE_RE.search(text):
            warnings.append(issue(
                "W_TEMPLATE_PAGE",
                "custom 页面缺少 <main class=\"page\"> 页面骨架（TEMPLATE.md §1）"))
        if not SECTION_TEMPLATE_RE.search(text):
            warnings.append(issue(
                "W_TEMPLATE_SECTION",
                "custom 页面缺少 <section class=\"section\"> 区块骨架（TEMPLATE.md §1）"))
        if H1_RE.search(text):
            warnings.append(issue(
                "W_TEMPLATE_H1",
                "custom 页面出现 <h1> 全局标题；标题/描述应由根壳项目栏统一提供（TEMPLATE.md §1）"))


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def print_human(report: dict, stream=None):
    stream = stream or sys.stdout
    summary = report["summary"]

    def out(line=""):
        stream.write(line + "\n")

    out("KittenPuppy4Ever 后端 module 校验（只读）")
    out("platform root: %s" % report["platform_root"])
    out("")

    out("Bases（kernel/registry.py 的 BASES + bases/*.json）:")
    for name in sorted(report["bases"]["registered"]):
        chain = report["bases"]["chains"].get(name) or []
        out("  %-10s -> %-14s chain=%s"
            % (name, report["bases"]["registered"][name], " <- ".join(chain)))
    if report["bases"]["errors"]:
        out("  Bases 错误:")
        for item in report["bases"]["errors"]:
            out("    ERROR [%s] %s" % (item["code"], item["message"]))
    if report["bases"]["warnings"]:
        out("  Bases 建议:")
        for item in report["bases"]["warnings"]:
            out("    WARN  [%s] %s" % (item["code"], item["message"]))
    out("")

    out("Global 检查:")
    if not report["global"]["errors"] and not report["global"]["warnings"]:
        out("  OK")
    for item in report["global"]["errors"]:
        out("  ERROR [%s] %s" % (item["code"], item["message"]))
    for item in report["global"]["warnings"]:
        out("  WARN  [%s] %s" % (item["code"], item["message"]))
    out("")

    out("模块清单（%d）:" % len(report["modules"]))
    for module in report["modules"]:
        effective = module["effective"]
        out("  %-4s %-16s base=%-9s view=%-6s path=%s"
            % (module["status"], module["id"],
               effective.get("base") or "-",
               effective.get("view_kind") or "-",
               effective.get("path") or "(missing)"))
        for item in module["errors"]:
            out("        ERROR [%s] %s" % (item["code"], item["message"]))
        for item in module["warnings"]:
            out("        WARN  [%s] %s" % (item["code"], item["message"]))
    out("")

    out("汇总: %d modules · PASS %d · FAIL %d · 硬性错误 %d · 建议 %d"
        % (summary["modules"], summary["pass"], summary["fail"],
           summary["errors"], summary["warnings"]))
    out("      module 错误 %d / base 错误 %d / global 错误 %d"
        % (summary["module_errors"], summary["base_errors"], summary["global_errors"]))
    out("退出码: %d（%s）"
        % (0 if report["ok"] else 1,
           "全部 PASS" if report["ok"] else "存在硬性错误"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="KittenPuppy4Ever 后端 module 只读校验器（rules: platform/MODULE_SPEC.md）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--root", default=None,
                        help="platform 根目录（默认为本脚本上一级目录）")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - 旧环境没有 reconfigure 时忽略
        pass

    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = os.path.abspath(root)
    layout_ok = (os.path.isdir(os.path.join(root, "projects"))
                 and os.path.isdir(os.path.join(root, "bases"))
                 and os.path.isfile(os.path.join(root, "kernel", "registry.py")))
    if not layout_ok:
        sys.stderr.write(
            "错误：%s 不像是 platform 根目录（需要 projects/、bases/、kernel/registry.py）\n" % root)
        return 2

    report = ModuleChecker(root).run()
    if args.json:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        print_human(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
