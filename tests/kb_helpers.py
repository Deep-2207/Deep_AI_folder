"""Temporary knowledge bases for tests (never touch the real knowledge/ and documents/ folders)."""
import tempfile
from pathlib import Path

from stockpatterns import knowledge
from stockpatterns.patterns import PATTERN_NAMES


def write_item(kb, kind, id_, status="PENDING_REVIEW", **meta):
    m = {"id": id_, "name": meta.pop("name", id_.replace("_", " ").title()), "kind": kind, "status": status, **meta}
    d = kb.folder(kind, status)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{id_}.md").write_text(knowledge.dump(m, f"# {m['name']}\n"), encoding="utf-8")


def make_kb(status="PENDING_REVIEW", patterns=PATTERN_NAMES, rule=None, model=None):
    """A KnowledgeBase in a temp folder with every coded pattern (implemented) and both strategies."""
    root = Path(tempfile.mkdtemp(prefix="kb_"))
    kb = knowledge.KnowledgeBase(root)
    for name in patterns:
        write_item(kb, "pattern", knowledge.slug(name), status, name=name, code_name=name,
                   implemented_in="stockpatterns/patterns.py")
    write_item(kb, "strategy", knowledge.RULE_STRATEGY, rule or status, implemented_in="stockpatterns/signal.py")
    write_item(kb, "strategy", knowledge.MODEL_STRATEGY, model or status, implemented_in="stockpatterns/learner.py")
    return kb
