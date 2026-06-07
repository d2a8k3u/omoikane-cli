"""Tree visualisation of ``delegation.json``."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static, Tree


class DelegationPane(Container):
    DEFAULT_CSS = """
    DelegationPane {
        border: tall $accent;
    }
    DelegationPane > Static.title {
        background: $boost;
        padding: 0 1;
    }
    DelegationPane > Tree {
        height: 1fr;
    }
    """

    def __init__(self, delegation_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.delegation_path = delegation_path

    def compose(self) -> ComposeResult:
        yield Static("Delegation tree", classes="title")
        yield Tree("project", id="delegation-tree")

    def refresh_tree(self) -> None:
        tree = self.query_one("#delegation-tree", Tree)
        tree.clear()
        data = self._load()
        nodes = {n["id"]: n for n in data.get("nodes", [])}
        edges = data.get("edges", [])
        children_by_parent: Dict[str, List[str]] = {}
        for edge in edges:
            children_by_parent.setdefault(edge["from"], []).append(edge["to"])

        root = tree.root
        root.label = "project"
        root.expand()
        self._fill(root, "n-root", nodes, children_by_parent)

    def _fill(self, parent_tree_node, node_id, nodes, children_by_parent, depth: int = 0):
        if depth > 30:
            return
        node = nodes.get(node_id)
        if node is None:
            return
        for child_id in children_by_parent.get(node_id, []):
            child = nodes.get(child_id)
            if not child:
                continue
            label = self._label_for(child, child_id)
            tree_child = parent_tree_node.add(label)
            tree_child.expand()
            self._fill(tree_child, child_id, nodes, children_by_parent, depth + 1)

    @staticmethod
    def _label_for(node: Dict[str, Any], node_id: str) -> str:
        actor = node.get("actor") or "?"
        task = node.get("task") or node_id
        text = node.get("label") or task
        return f"{actor} :: {text[:60]}"

    def _load(self) -> Dict[str, Any]:
        if not self.delegation_path.exists():
            return {"nodes": [], "edges": []}
        try:
            return json.loads(self.delegation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"nodes": [], "edges": []}
