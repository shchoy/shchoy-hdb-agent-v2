"""Neptune openCypher bulk-load CSVs: one `nodes_<Label>.csv` per label and one `edges.csv`.

Node files: `:ID`, `:LABEL`, then `name`, `search_name` and the label's properties, each typed (`status:String`).
Edge files: `:ID`, `:START_ID`, `:END_ID`, `:TYPE`. Every ID is a string business ID.
"""

from __future__ import annotations

import csv
from pathlib import Path

from plg.entities.model import Edge, GraphData, Node, Scalar

EDGE_HEADER = [":ID", ":START_ID", ":END_ID", ":TYPE"]
NODE_FIXED = [":ID", ":LABEL", "name:String", "search_name:String"]
NEPTUNE_TYPES = {"String", "Int", "Double", "Bool"}


def column_type(value: Scalar) -> str:
    if isinstance(value, bool):
        return "Bool"
    if isinstance(value, int):
        return "Int"
    if isinstance(value, float):
        return "Double"
    return "String"


def node_header(nodes: list[Node]) -> list[str]:
    types: dict[str, str] = {}
    for node in nodes:
        for key, value in node.props.items():
            types.setdefault(key, column_type(value))
    return [*NODE_FIXED, *(f"{k}:{t}" for k, t in sorted(types.items()))]


def node_row(node: Node, header: list[str]) -> list[str]:
    row = {":ID": node.id, ":LABEL": node.label, "name:String": node.name, "search_name:String": node.search_name}
    cells = []
    for column in header:
        if column in row:
            cells.append(row[column])
            continue
        value = node.props.get(column.rsplit(":", 1)[0])
        cells.append("" if value is None else str(value).lower() if isinstance(value, bool) else str(value))
    return cells


def write_nodes(path: Path, label: str, nodes: list[Node]) -> None:
    """Write the nodes of one label to `nodes_<label>.csv`, replacing the file."""
    header = node_header(nodes)
    with (path / f"nodes_{label}.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(node_row(n, header) for n in nodes)


def write_edges(path: Path, edges: list[Edge], append: bool = False) -> None:
    path = path / "edges.csv"
    new = not (append and path.exists())
    with path.open("w" if new else "a", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(EDGE_HEADER)
        writer.writerows([e.id, e.start, e.end, e.type] for e in edges)


def write_graph(path: Path, data: GraphData) -> None:
    path.mkdir(parents=True, exist_ok=True)
    by_label: dict[str, list[Node]] = {}
    for node in data.nodes.values():
        by_label.setdefault(node.label, []).append(node)
    for label, nodes in sorted(by_label.items()):
        write_nodes(path, label, nodes)
    write_edges(path, list(data.edges.values()))


def _coerce(value: str, column: str) -> Scalar | None:
    if value == "":
        return None
    kind = column.rsplit(":", 1)[1]
    return {"Int": int, "Double": float, "Bool": lambda v: v == "true"}.get(kind, str)(value)  # type: ignore[no-any-return,operator]


def read_graph(*dirs: Path) -> GraphData:
    """Load the CSVs of each directory in order; later directories add to (and may overwrite) earlier ones."""
    data = GraphData()
    for directory in dirs:
        for file in sorted(directory.glob("nodes_*.csv")):
            with file.open(newline="") as f:
                reader = csv.reader(f)
                header: list[str] = next(reader)
                for row in reader:
                    cells = dict(zip(header, row, strict=True))
                    props = {
                        c.rsplit(":", 1)[0]: v
                        for c in header[len(NODE_FIXED):]
                        if (v := _coerce(cells[c], c)) is not None
                    }
                    data.add_node(Node(id=cells[":ID"], label=cells[":LABEL"], name=cells["name:String"], props=props))
        edges = directory / "edges.csv"
        if edges.exists():
            with edges.open(newline="") as f:
                for record in csv.DictReader(f):
                    data.add_edge(Edge(type=record[":TYPE"], start=record[":START_ID"], end=record[":END_ID"]))
    return data
