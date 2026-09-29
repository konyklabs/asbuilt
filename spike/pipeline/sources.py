"""Every source document in an ingest root, with its version and
lastmodified: the versioned document a fact cites (D-013, stage 1).

Per kind (``bench/protocol.py``'s document ids):

- ``wiki/<slug>``: ``sources/wiki/*.md`` front matter ``version`` and
  ``lastmodified``; locations are ``#heading`` anchors (GitHub's slug rule).
- ``doc/<id>``: ``sources/docs/*.md`` front matter ``headRevisionId`` (the
  version) and ``modifiedTime``; anchors likewise.
- ``ticket/<KEY>``: ``sources/tickets/*.json``; version and lastmodified are
  ``updated``; locations are ``description`` and each ``comment-<k>``.
- ``pull/<n>``: ``sources/pulls/*.json``; version and lastmodified are the
  latest of ``closed``, ``opened`` and each comment's ``created``; locations
  are ``body`` and each ``comment-<k>``.
- ``run/<id>``: ``runs/*.json``; version is the run's commit.
- ``code/<path>``: every file in the repository at the step; version and
  lastmodified are the commit that last changed it (``GitHistory``).

``SourceDocument.text`` is what an extractor reads; ``anchors`` are the
locations a citation into it may name.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from pipeline.history import GitHistory
from pipeline.store import Document

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
TEXT_KINDS = ("wiki", "doc", "ticket", "pull")


def github_slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text)


def _parse_dt(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@dataclass(frozen=True)
class SourceDocument:
    document: Document
    text: str = ""
    anchors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def id(self) -> str:
        return self.document.id


def _hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _front_matter(raw: str) -> tuple[dict, str]:
    if raw.startswith("---"):
        parts = raw.split("\n---", 1)
        if len(parts) == 2:
            meta = yaml.safe_load(parts[0][3:]) or {}
            return meta, parts[1].lstrip("-\n")
    return {}, raw


def read_markdown(path: Path, kind: str) -> SourceDocument:
    raw = path.read_text()
    meta, body = _front_matter(raw)
    slugs = tuple(f"#{github_slug(h)}" for h in _HEADING.findall(body))
    if kind == "wiki":
        doc_id = meta.get("id") or f"wiki/{path.stem}"
        version = meta.get("version")
        lastmodified = _parse_dt(meta.get("lastmodified"))
        source = "wiki"
    else:
        doc_id = meta.get("id") or f"doc/{path.stem}"
        version = meta.get("headRevisionId")
        lastmodified = _parse_dt(meta.get("modifiedTime"))
        source = "docs"
    return SourceDocument(
        document=Document(
            id=str(doc_id),
            source=source,
            kind=kind,
            version=None if version is None else str(version),
            lastmodified=lastmodified,
            title=meta.get("title"),
            content_hash=_hash(raw.encode()),
        ),
        text=body,
        anchors=slugs,
    )


def _thread_text(title: str, lead_label: str, lead: str, comments: list[dict]) -> str:
    lines = [f"# {title}", "", f"[{lead_label}]", lead or "(empty)"]
    for comment in comments:
        lines += [
            "",
            f"[{comment.get('id')}] {comment.get('author', '?')} at {comment.get('created', '?')}:",
            comment.get("body", ""),
        ]
    return "\n".join(lines)


def read_ticket(path: Path) -> SourceDocument:
    raw = path.read_text()
    data = json.loads(raw)
    comments = data.get("comments") or []
    header = (
        f"{data.get('key')}: {data.get('summary')} "
        f"(status {data.get('status')}, type {data.get('type')}, "
        f"labels {', '.join(data.get('labels') or [])})"
    )
    return SourceDocument(
        document=Document(
            id=data.get("id") or f"ticket/{data.get('key', path.stem)}",
            source="tickets",
            kind="ticket",
            version=str(data.get("updated") or ""),
            lastmodified=_parse_dt(data.get("updated")),
            title=data.get("summary"),
            content_hash=_hash(raw.encode()),
        ),
        text=_thread_text(header, "description", data.get("description", ""), comments),
        anchors=("description", *(str(c.get("id")) for c in comments)),
    )


def read_pull(path: Path) -> SourceDocument:
    raw = path.read_text()
    data = json.loads(raw)
    comments = data.get("comments") or []
    stamps = [
        d
        for d in (_parse_dt(data.get("closed")), _parse_dt(data.get("opened")))
        + tuple(_parse_dt(c.get("created")) for c in comments)
        if d is not None
    ]
    latest = max(stamps) if stamps else None
    header = (
        f"Pull request #{data.get('number')}: {data.get('title')} "
        f"({data.get('state')}; files: {', '.join(data.get('files') or [])})"
    )
    return SourceDocument(
        document=Document(
            id=data.get("id") or f"pull/{data.get('number', path.stem)}",
            source="pulls",
            kind="pull",
            version=latest.isoformat() if latest else None,
            lastmodified=latest,
            title=data.get("title"),
            content_hash=_hash(raw.encode()),
        ),
        text=_thread_text(header, "body", data.get("body", ""), comments),
        anchors=("body", *(str(c.get("id")) for c in comments)),
    )


def read_text_sources(root: Path) -> list[SourceDocument]:
    docs: list[SourceDocument] = []
    for path in sorted((root / "sources" / "wiki").glob("*.md")):
        docs.append(read_markdown(path, "wiki"))
    for path in sorted((root / "sources" / "docs").glob("*.md")):
        docs.append(read_markdown(path, "doc"))
    for path in sorted((root / "sources" / "tickets").glob("*.json")):
        docs.append(read_ticket(path))
    for path in sorted((root / "sources" / "pulls").glob("*.json")):
        docs.append(read_pull(path))
    return docs


def read_run_documents(root: Path, history: GitHistory | None = None) -> list[SourceDocument]:
    docs = []
    for path in sorted((root / "runs").glob("*.json")):
        raw = path.read_bytes()
        metadata = json.loads(raw).get("metadata") or {}
        step = metadata.get("step")
        lastmodified = None
        if history is not None and step in history.step_ids:
            lastmodified = history.date(step)
        docs.append(
            SourceDocument(
                document=Document(
                    id=f"run/{path.stem}",
                    source="runs",
                    kind="run",
                    version=metadata.get("commit"),
                    lastmodified=lastmodified,
                    title=f"{path.stem} at {step}",
                    content_hash=_hash(raw),
                )
            )
        )
    return docs


def code_documents(history: GitHistory, step_id: str) -> list[SourceDocument]:
    docs = []
    for path, sha in sorted(history.tree(step_id).items()):
        changed = history.last_change(path, step_id)
        docs.append(
            SourceDocument(
                document=Document(
                    id=f"code/{path}",
                    source="repo",
                    kind="code",
                    version=changed.sha if changed else None,
                    lastmodified=changed.date if changed else None,
                    title=path,
                    content_hash=sha,
                )
            )
        )
    return docs
