"""The engineering graph: what the system knows, as nodes and typed edges.

The knowledge is already here — functions in ``knowledge.functions``, calculators
in ``calc``, standards in ``knowledge.source``, components in the ingested
catalogues, interfaces in the ``Requires`` lists. What is missing is a single
structure over all of it, so that a planner can reason about *support rotation*
without knowing that bearings live in a JSON file and ISO 286 lives in a Python
dict.

**The graph is derived, never authored.** This is the whole design. A graph
maintained by hand beside the code is a graph that is wrong within a week: the
first person to add a calculator and forget the node has silently broken every
answer that depends on it, and nothing fails. So ``build()`` reads the same
registries the runtime reads. A node exists because the thing exists. If a
family declares a function, the edge is there; if it stops declaring it, the
edge is gone, and no one has to remember.

The cost is that the graph can only contain what the code already exposes, and
the gaps are visible in ``coverage()`` rather than papered over. That is the
right trade: a gap you can see is a roadmap, and a stub you cannot distinguish
from a fact is a liability.

**An explanation is a traversal record, not a second system.** "Why this
bearing?" is answered by the path actually walked to reach it —
``explain_selection`` replays the edges the chain used, and each carries the
calculator, standard or dataset responsible. Building the explanation
separately from the reasoning would let the two disagree, and a plausible story
about a decision is exactly the failure the deterministic stages exist to
prevent.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

# --------------------------------------------------------------------------- #
# the vocabulary
# --------------------------------------------------------------------------- #
FUNCTION = "Function"
REQUIREMENT = "Requirement"
CONSTRAINT = "Constraint"
FAILURE_MODE = "FailureMode"
COMPONENT = "Component"
INTERFACE = "Interface"
CALCULATION = "Calculation"
STANDARD = "Standard"
PROCESS = "ManufacturingProcess"

NODE_KINDS = (FUNCTION, REQUIREMENT, CONSTRAINT, FAILURE_MODE, COMPONENT,
              INTERFACE, CALCULATION, STANDARD, PROCESS)

#: Edges are directed and typed. The type is what makes the graph reasonable
#: over: "requires" walks toward work the design still owes, "validated_by"
#: walks toward the thing that would catch an error, and they must not be
#: confused — one is a task list and the other is an audit trail.
IMPLEMENTS = "implements"          # Component -> Function
REQUIRES = "requires"              # Component|Function -> Interface|Component
VALIDATED_BY = "validated_by"      # Component|Interface -> Calculation|Standard
CAN_FAIL_BY = "can_fail_by"        # Component -> FailureMode
GOVERNED_BY = "governed_by"        # FailureMode|Calculation -> Standard
SOURCED_FROM = "sourced_from"      # Component -> Standard (the catalogue)
CONSTRAINS = "constrains"          # Constraint -> Component|Interface
MADE_BY = "made_by"                # Component|Interface -> ManufacturingProcess

EDGE_KINDS = (IMPLEMENTS, REQUIRES, VALIDATED_BY, CAN_FAIL_BY, GOVERNED_BY,
              SOURCED_FROM, CONSTRAINS, MADE_BY)


@dataclass(frozen=True)
class Node:
    kind: str
    id: str
    label: str = ""
    attrs: tuple[tuple[str, Any], ...] = ()

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"

    def get(self, name: str, default: Any = None) -> Any:
        return dict(self.attrs).get(name, default)

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"kind": self.kind, "id": self.id}
        if self.label:
            out["label"] = self.label
        if self.attrs:
            out["attrs"] = dict(self.attrs)
        return out


@dataclass(frozen=True)
class Edge:
    """A relationship, and what makes it true.

    ``why`` is not decoration. An edge with no justification is an assertion
    nobody can check, and the point of the graph is that every step of an
    answer names the calculator, standard or dataset behind it.
    """

    kind: str
    src: str                       # Node.key
    dst: str                       # Node.key
    why: str = ""

    def to_dict(self) -> dict:
        out = {"kind": self.kind, "src": self.src, "dst": self.dst}
        if self.why:
            out["why"] = self.why
        return out


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    _out: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))
    _in: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))

    # -- construction ------------------------------------------------------- #
    def add(self, node: Node) -> Node:
        """Idempotent. A node harvested twice keeps the richer label."""
        existing = self.nodes.get(node.key)
        if existing is None:
            self.nodes[node.key] = node
            return node
        if node.label and not existing.label:
            merged = Node(existing.kind, existing.id, node.label,
                          tuple({**dict(existing.attrs), **dict(node.attrs)}
                                .items()))
            self.nodes[node.key] = merged
            return merged
        return existing

    def link(self, kind: str, src: Node, dst: Node, why: str = "") -> Edge:
        self.add(src)
        self.add(dst)
        edge = Edge(kind, src.key, dst.key, why)
        if edge not in self.edges:
            self.edges.append(edge)
            self._out[src.key].append(edge)
            self._in[dst.key].append(edge)
        return edge

    # -- query -------------------------------------------------------------- #
    def node(self, kind: str, id_: str) -> Optional[Node]:
        return self.nodes.get(f"{kind}:{id_}")

    def of_kind(self, kind: str) -> list[Node]:
        return sorted((n for n in self.nodes.values() if n.kind == kind),
                      key=lambda n: n.id)

    def out(self, key: str, kind: str = "") -> list[Edge]:
        return [e for e in self._out.get(key, ()) if not kind or e.kind == kind]

    def into(self, key: str, kind: str = "") -> list[Edge]:
        return [e for e in self._in.get(key, ()) if not kind or e.kind == kind]

    def neighbours(self, key: str, kind: str = "") -> list[Node]:
        return [self.nodes[e.dst] for e in self.out(key, kind)
                if e.dst in self.nodes]

    def walk(self, start: str, kinds: tuple[str, ...] = EDGE_KINDS,
             depth: int = 6) -> Iterator[tuple[int, Edge]]:
        """Breadth-first over the chosen edge types.

        Depth-limited because the graph has cycles by design — a component
        requires an interface which is validated by a standard which sources
        components — and an unbounded walk is a hang, not an answer.
        """
        seen, queue = {start}, deque([(0, start)])
        while queue:
            level, key = queue.popleft()
            if level >= depth:
                continue
            for edge in self._out.get(key, ()):
                if edge.kind not in kinds:
                    continue
                yield level, edge
                if edge.dst not in seen:
                    seen.add(edge.dst)
                    queue.append((level + 1, edge.dst))

    def to_dict(self) -> dict:
        return {"nodes": [n.to_dict() for n in self.nodes.values()],
                "edges": [e.to_dict() for e in self.edges]}

    def __len__(self) -> int:
        return len(self.nodes)


# --------------------------------------------------------------------------- #
# harvest
# --------------------------------------------------------------------------- #
def _standard_nodes(graph: Graph, text: str, cited_by: Node,
                    why: str = "") -> None:
    """Attach the standards named in a citation string.

    Citations are prose because that is how they read best to an engineer, so
    the standard is recovered by looking for its designation. Anything not
    recognisable as a standard is left alone rather than guessed at — a
    Standard node invented from a half-matched string is worse than no node,
    because it looks like a source.
    """
    import re

    for match in re.finditer(r"\b(ISO|DIN|EN|ASME|ANSI|JIS|BS|SAE|NASA-STD)"
                             r"[\s-]?(\d{2,5}(?:-\d+)?)", text):
        designation = f"{match.group(1)} {match.group(2)}"
        graph.link(VALIDATED_BY, cited_by,
                   Node(STANDARD, designation, designation),
                   why or text.strip())


def build() -> Graph:
    """Harvest the graph from the registries the runtime already uses.

    Nothing here is a literal list of nodes. Every one is read from the thing
    that defines it, so the graph cannot describe a system the code does not
    actually have.
    """
    from orion import calc
    from orion.knowledge import functions as F
    from orion.knowledge.registry import dataset_for_family, rows_for_family
    from orion.skills.base import registry as skills

    F.load_all()
    graph = Graph()

    # 1. Functions. The vocabulary is the definition; the intent line is the
    #    label a planner reads when choosing between them.
    for function in F.FUNCTIONS:
        graph.add(Node(FUNCTION, function, F.INTENT.get(function, "")))

    # 2. Components and what they claim. Read through one representative row
    #    per family, because `Implements` is computed per row and the functional
    #    claim is a property of the family rather than of the individual part.
    for family in sorted(set(F._IMPLEMENTS) | set(F._SATISFIERS)):
        rows = rows_for_family(family)
        component = graph.add(Node(COMPONENT, family, family.replace("_", " "),
                                   (("rows", len(rows)),)))
        if rows:
            for impl in F.implements_for(family, rows[0]):
                function = graph.add(Node(FUNCTION, impl.function,
                                          F.INTENT.get(impl.function, "")))
                # An unjustified edge is an assertion nobody can check, so the
                # function's own intent stands in when a family declares the
                # claim without arguing for it. Weaker than a real note, but it
                # keeps the invariant structural rather than dependent on
                # whoever wrote the declaration remembering.
                graph.link(IMPLEMENTS, component, function,
                           impl.note or F.INTENT.get(impl.function, "declared"))
                # The debt: what the design owes a component it chooses.
                for req in impl.requires:
                    interface = graph.add(Node(
                        INTERFACE, req.interface_kind,
                        req.interface_kind.replace("_", " "),
                        (("optional", req.optional),)))
                    graph.link(REQUIRES, component, interface, req.detail)

        # Where the rows came from. A component with no source is a component
        # nobody can audit.
        data = dataset_for_family(family) or {}
        source = data.get("source") or {}
        maker, document = source.get("manufacturer", ""), source.get("document", "")
        # "SKF" + "SKF bearings and mounted products" reads as a stutter.
        label = (document if maker and document.startswith(maker)
                 else " ".join(x for x in (maker, document) if x))
        if label:
            graph.link(SOURCED_FROM, component,
                       Node(STANDARD, label, label,
                            (("edition", source.get("edition", "")),
                             ("loader_version",
                              source.get("loader_version", "")))),
                       f"{len(rows)} rows ingested")
        if source.get("standard"):
            _standard_nodes(graph, source["standard"], component,
                            "boundary dimensions and tolerances")

    # 3. Calculators. Every one is a node whether or not anything cites it yet;
    #    an unreferenced calculator is a real finding, not an omission.
    for name in calc.CALCULATORS:
        doc = (calc.CALCULATORS[name].__doc__ or "").strip().splitlines()
        node = graph.add(Node(CALCULATION, name,
                              doc[0].strip() if doc else ""))
        if doc:
            _standard_nodes(graph, " ".join(doc[:6]), node,
                            "the standard the method is taken from")

    # 4. Skills tie functions to the calculators and standards they rest on.
    #    This is the edge that makes "which standard decided this number"
    #    answerable without reading the skill's source.
    for name in skills.names():
        skill = skills.get(name)
        if skill is None:
            continue
        for function in skill.graph.functions:
            fn_node = graph.add(Node(FUNCTION, function,
                                     F.INTENT.get(function, "")))
            for calculator in skill.graph.calculators:
                graph.link(VALIDATED_BY, fn_node,
                           Node(CALCULATION, calculator, ""),
                           f"used by skill {name}")
            for standard in skill.graph.standards:
                _standard_nodes(graph, standard, fn_node,
                                f"cited by skill {name}")

    # 5. Failure modes, if the knowledge base has any. Absent rather than
    #    stubbed when it does not — `coverage()` reports the hole.
    try:
        from orion.knowledge import failure_modes as FM
    except ImportError:
        return graph
    from orion.knowledge.registry import CATALOGUES

    for mode in FM.MODES:
        node = graph.add(Node(FAILURE_MODE, mode.id, mode.label,
                              (("driver", mode.driver),)))
        for family in mode.applies_to:
            rows = rows_for_family(family)
            if not rows:
                continue
            # Bearing types are views over one catalogue, so their rows are the
            # same rows. Marked, so `coverage()` can count families and rows
            # without reporting 615 rows across 11 families when there are 615
            # rows across 2.
            attrs: tuple[tuple[str, Any], ...] = (("rows", len(rows)),)
            if family not in CATALOGUES:
                attrs += (("view_of", "rolling_bearing"),)
            graph.link(CAN_FAIL_BY, graph.add(Node(COMPONENT, family,
                                                   family.replace("_", " "),
                                                   attrs)),
                       node, mode.mechanism)
        if mode.governed_by:
            _standard_nodes(graph, mode.governed_by, node, mode.mechanism)
        if mode.calculator:
            graph.link(VALIDATED_BY, node,
                       Node(CALCULATION, mode.calculator, ""),
                       f"assessed by {mode.calculator}")
    return graph


_GRAPH: Optional[Graph] = None


def graph() -> Graph:
    """The built graph, cached. Call ``rebuild()`` after registering anything."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build()
    return _GRAPH


def rebuild() -> Graph:
    global _GRAPH
    _GRAPH = build()
    return _GRAPH


# --------------------------------------------------------------------------- #
# reasoning over the graph
# --------------------------------------------------------------------------- #
def components_for(function: str) -> list[Node]:
    """What claims to perform a function. The planner's entry point.

    Note the direction: this asks the graph, not a hard-coded map from function
    to family. A family that stops declaring the function disappears from the
    answer without anyone editing this.
    """
    g = graph()
    key = f"{FUNCTION}:{function}"
    return sorted((g.nodes[e.src] for e in g.into(key, IMPLEMENTS)
                   if e.src in g.nodes), key=lambda n: n.id)


def obligations(family: str) -> list[tuple[Node, str]]:
    """The interfaces a family's components oblige the design to provide.

    This is what turns "pick a bearing" into "pick a bearing and then you owe
    it a shoulder". A planner that does not track these produces a part
    floating in space.
    """
    g = graph()
    key = f"{COMPONENT}:{family}"
    return [(g.nodes[e.dst], e.why) for e in g.out(key, REQUIRES)
            if e.dst in g.nodes]


def failure_modes(family: str) -> list[tuple[Node, str]]:
    g = graph()
    key = f"{COMPONENT}:{family}"
    return [(g.nodes[e.dst], e.why) for e in g.out(key, CAN_FAIL_BY)
            if e.dst in g.nodes]


def authorities(key: str) -> list[Node]:
    """The standards and calculators that would catch an error in a node."""
    g = graph()
    return [g.nodes[e.dst] for e in g.out(key, VALIDATED_BY)
            if e.dst in g.nodes]


def explain_selection(chain: Any) -> dict:
    """"Why was this component selected?", as the path actually walked.

    Replays the chain's own stages against the graph rather than reconstructing
    a justification. Every edge carries the calculator, standard or dataset
    responsible, and an edge the chain did not use does not appear — which is
    what makes this a record rather than a story.
    """
    from orion import reasoning as R

    g = graph()
    selection = chain.step(R.SELECTION)
    if selection is None or not chain.complete:
        return {"answer": f"no component was selected; the chain stopped at "
                          f"{chain.stopped_at}",
                "path": [], "asks": chain.asks()}

    candidate = selection.detail["_candidate"]
    requirements = chain.step(R.REQUIREMENTS)
    duty = requirements.detail["duty"] if requirements else {}

    # The decision has a shape, and flattening it loses the shape. There is one
    # spine — the requirement narrowed to a function narrowed to a family
    # narrowed to a part — and everything else hangs off the part: what
    # validated it, where it came from, what it now obliges. Rendering all of it
    # as one list repeats the part once per fact and reads like noise.
    stated = ", ".join(f"{k}={v:g}" for k, v in sorted(duty.items())
                       if isinstance(v, (int, float)) and v)
    evidence = ", ".join(f"{k}={v}" for k, v in candidate.evidence.items()
                         if k not in ("basis",))
    spine = [
        {"node": "Requirement", "why": stated or "as stated"},
        {"node": f"Function {candidate.function}",
         "why": "the function the request resolves to"},
        {"node": f"Component {candidate.family}",
         "why": f"declares {candidate.function}", "edge": IMPLEMENTS},
        {"node": candidate.designation, "why": evidence, "edge": "satisfies"},
    ]

    seen: set[str] = set()
    validated = []
    for node in authorities(f"{FUNCTION}:{candidate.function}"):
        if node.key not in seen:
            seen.add(node.key)
            validated.append({"node": f"{node.kind} {node.id}",
                              "why": node.label or "governs the calculation"})

    owed = []
    for node, why in obligations(candidate.family):
        if node.key in seen:
            continue                     # an interface owed by two functions
        seen.add(node.key)
        owed.append({"node": f"Interface {node.id}", "why": why,
                     "validated_by": [f"{a.kind} {a.id}"
                                      for a in authorities(node.key)]})

    source = [{"node": f"Dataset {n.id}",
               "why": f"edition {n.get('edition') or '?'}, loader "
                      f"v{n.get('loader_version') or '?'}"}
              for e in g.out(f"{COMPONENT}:{candidate.family}", SOURCED_FROM)
              if (n := g.nodes.get(e.dst))]

    risks = selection.detail.get("risks", [])
    return {"answer": f"{candidate.designation} was selected to "
                      f"{candidate.function}",
            "spine": spine, "validated_by": validated, "requires": owed,
            "sourced_from": source,
            "failure_modes": [n.id for n, _ in failure_modes(candidate.family)],
            "risks": risks,
            "citations": chain.citations, "warnings": chain.warnings}


def render_path(explanation: dict) -> str:
    """The dependency chain: one spine, with what hangs off its end."""
    if not explanation.get("spine"):
        lines = [explanation["answer"]]
        lines += [f"  ASKS: {q}" for q in explanation.get("asks", ())]
        return "\n".join(lines)

    lines = [explanation["answer"], ""]
    for i, hop in enumerate(explanation["spine"]):
        if i:
            lines.append(f"  |  {hop['why']}".rstrip())
            lines.append("  v")
        lines.append(hop["node"])
        if not i and hop["why"]:
            lines[-1] = f"{hop['node']}  ({hop['why']})"

    for label, key in (("validated by", "validated_by"),
                       ("sourced from", "sourced_from")):
        for item in explanation.get(key, ()):
            lines.append(f"    {label:14s} {item['node']}"
                         + (f"  — {item['why']}" if item["why"] else ""))

    if explanation.get("requires"):
        lines.append("    owes the design")
        for item in explanation["requires"]:
            lines.append(f"      {item['node']:24s} {item['why']}")
            for auth in item["validated_by"]:
                lines.append(f"        {'per':>22s} {auth}")

    risks = [r for r in explanation.get("risks", ())
             if r.get("verdict") in ("at_risk", "marginal")]
    if risks:
        lines.append("    at risk of")
        for r in risks:
            lines.append(f"      {r['mode']:24s} {r['finding']}")
    if explanation.get("failure_modes"):
        lines.append("    can fail by     "
                     + ", ".join(explanation["failure_modes"]))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# coverage
# --------------------------------------------------------------------------- #
def coverage() -> dict:
    """What the system can engineer, counted in capability rather than files.

    A file count says nothing: 600 bearings that all serve one function is
    narrower than three families that serve five. What matters is how many
    functions can be taken from a stated duty all the way to verified geometry,
    and every stage that drops out along the way is a specific piece of work.
    """
    from orion import calc
    from orion.knowledge import functions as F
    from orion.skills.base import registry as skills

    F.load_all()
    g = graph()

    per_function: dict[str, dict] = {}
    for function in F.FUNCTIONS:
        families = [n.id for n in components_for(function)]
        rows = sum(int(g.node(COMPONENT, f).get("rows", 0) or 0)
                   for f in families if g.node(COMPONENT, f))
        selectable = function in {fn for fns in F._SATISFIERS.values()
                                  for fn in fns}
        buildable = bool(skills.for_function(function))
        per_function[function] = {
            "families": families,
            "rows": rows,
            "selectable": selectable,        # a duty can be searched
            "buildable": buildable,          # a skill turns it into geometry
            "failure_modes": sorted({m for fam in families
                                     for m, _ in
                                     [(n.id, w) for n, w in
                                      failure_modes(fam)]}),
        }

    complete = [fn for fn, s in per_function.items()
                if s["selectable"] and s["buildable"]]
    partial = [fn for fn, s in per_function.items()
               if s["selectable"] != s["buildable"]]
    absent = [fn for fn, s in per_function.items()
              if not s["selectable"] and not s["buildable"]]

    referenced = {n.id for n in g.of_kind(CALCULATION)
                  if g.into(n.key, VALIDATED_BY)}
    return {
        "functions": {"total": len(F.FUNCTIONS), "complete": sorted(complete),
                      "partial": sorted(partial), "absent": sorted(absent)},
        # Views are excluded from both counts: they are the same rows under a
        # narrower name, and adding them up says the catalogue is five times
        # the size it is.
        "components": {
            "families": len([n for n in g.of_kind(COMPONENT)
                             if not n.get("view_of")]),
            "views": len([n for n in g.of_kind(COMPONENT) if n.get("view_of")]),
            "rows": sum(int(n.get("rows", 0) or 0) for n in g.of_kind(COMPONENT)
                        if not n.get("view_of"))},
        "calculators": {"total": len(calc.CALCULATORS),
                        "reachable_from_a_function": sorted(referenced),
                        "orphaned": sorted(set(calc.CALCULATORS) - referenced)},
        "standards": [n.id for n in g.of_kind(STANDARD)],
        "skills": skills.names(),
        "failure_modes": len(g.of_kind(FAILURE_MODE)),
        "processes": len(g.of_kind(PROCESS)),
        "graph": {"nodes": len(g.nodes), "edges": len(g.edges)},
        "per_function": per_function,
    }


def report() -> str:
    """Coverage as a page, for a human deciding what to build next."""
    c = coverage()
    fn = c["functions"]
    lines = [
        "ENGINEERING COVERAGE",
        "",
        f"  graph          {c['graph']['nodes']} nodes, "
        f"{c['graph']['edges']} edges",
        f"  components     {c['components']['families']} families "
        f"({c['components']['views']} type views), "
        f"{c['components']['rows']} rows",
        f"  calculators    {c['calculators']['total']} "
        f"({len(c['calculators']['orphaned'])} not reachable from any function)",
        f"  standards      {len(c['standards'])}",
        f"  skills         {len(c['skills'])}",
        f"  failure modes  {c['failure_modes']}",
        f"  processes      {c['processes']}",
        "",
        f"FUNCTIONS  {len(fn['complete'])}/{fn['total']} end to end",
        "",
    ]
    for function, s in sorted(c["per_function"].items()):
        if s["selectable"] and s["buildable"]:
            mark, note = "OK  ", f"{s['rows']} rows in {len(s['families'])}"
        elif s["selectable"]:
            mark, note = "part", "selectable, but no skill builds geometry"
        elif s["buildable"]:
            mark, note = "part", "a skill exists, but no catalogue to select from"
        else:
            mark, note = "--  ", "no components, no skill"
        modes = (f"; {len(s['failure_modes'])} failure modes"
                 if s["failure_modes"] else "; no failure modes")
        lines.append(f"  {mark} {function:24s} {note}{modes}")
    if c["calculators"]["orphaned"]:
        lines += ["", "CALCULATORS NOT REACHABLE FROM ANY FUNCTION",
                  "  " + ", ".join(c["calculators"]["orphaned"])]
    return "\n".join(lines)
