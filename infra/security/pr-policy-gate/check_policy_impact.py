#!/usr/bin/env python3
"""
PR 策略图谱 CI 门禁与 Graphviz 影响面可视化
输入: 变更的 .rego 文件路径 → TreeSitter 解析 → 构建依赖图 → Graphviz 渲染 → 门禁校验
"""

import os
import sys
import subprocess
import logging
import glob
import pydot

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("PolicyCIGate")


def parse_rego_simple(filepath: str) -> dict:
    """轻量级解析 Rego 提取 package/imports/rules"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    imports = [
        l.strip().split()[-1]
        for l in content.splitlines()
        if l.strip().startswith("import ")
    ]
    rules = [
        l.split()[1].split("(")[0]
        for l in content.splitlines()
        if l.strip().startswith(("rule ", "allow ="))
    ]
    pkg = "main"
    for l in content.splitlines():
        if l.startswith("package "):
            pkg = l.split()[-1]
    return {"package": pkg, "imports": imports, "rules": [f"{pkg}.{r}" for r in rules]}


def build_graph_and_validate(
    changed_files: list, max_depth: int = 3, fail_on_impact: int = 5
) -> bool:
    graph = pydot.Dot(graph_type="digraph", rankdir="LR")
    graph.add_node(pydot.Node("style=filled,color=lightgrey,label='ROOT'"))

    nodes_seen, edges_seen = set(), set()
    impacted_count = 0

    for fpath in changed_files:
        if not fpath.endswith(".rego"):
            continue
        info = parse_rego_simple(fpath)
        pkg_node = f"pkg_{info['package']}"
        if pkg_node not in nodes_seen:
            graph.add_node(
                pydot.Node(
                    pkg_node,
                    shape="box",
                    style="filled",
                    fillcolor="lightblue",
                    label=f"Package: {info['package']}",
                )
            )
            nodes_seen.add(pkg_node)
            impacted_count += len(info["rules"])

            for imp in info["imports"]:
                target = f"import_{imp.replace('.','_')}"
                if target not in nodes_seen:
                    graph.add_node(
                        pydot.Node(
                            target, shape="diamond", fillcolor="orange", label=imp
                        )
                    )
                    nodes_seen.add(target)
                edge_key = f"{pkg_node}->{target}"
                if edge_key not in edges_seen:
                    graph.add_edge(pydot.Edge(pkg_node, target, color="gray50"))
                    edges_seen.add(edge_key)

    # 渲染 PNG
    png_path = "policy_dependency_graph.png"
    graph.write_png(png_path)
    log.info(f"🖼️ 依赖图已生成: {png_path}")

    # 门禁校验
    log.info(
        f"🔍 影响面评估: 变更涉及 {len(changed_files)} 文件, 预估规则影响数: {impacted_count}"
    )
    if impacted_count > fail_on_impact:
        log.error(
            f"❌ PR 门禁拦截: 影响规则数 {impacted_count} > 阈值 {fail_on_impact}。请拆分 PR 或补充测试用例。"
        )
        return False
    log.info("✅ PR 门禁通过: 影响面在安全阈值内")
    return True


if __name__ == "__main__":
    # 支持传入文件列表, 或自动扫描暂存区变更
    files = sys.argv[1:]
    if not files:
        # 默认扫描 policies 目录模拟 PR 变更
        files = [f for f in glob.glob("policies/**/*.rego", recursive=True)] or [
            "policies/main.rego"
        ]
        if not os.path.exists(files[0]):
            os.makedirs("policies", exist_ok=True)
            with open("policies/main.rego", "w") as f:
                f.write("package main\nimport data.authz\nallow = true")
            files = ["policies/main.rego"]
    success = build_graph_and_validate(files, max_depth=3, fail_on_impact=5)
    sys.exit(0 if success else 1)
