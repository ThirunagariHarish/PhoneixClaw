"""
Tiny stdlib-only RSS / Atom parser.

We deliberately avoid pulling in feedparser as a new dependency for
v1.0; the PM news feeds we target all conform to standard RSS 2.0 or
Atom 1.0 and we only need title/link/description/pubDate.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

from .base import parse_rss_datetime


ATOM_NS = "{http://www.w3.org/2005/Atom}"


@dataclass
class RSSEntry:
    title: str
    link: str
    summary: str
    published_at: datetime


def parse_feed(body: str) -> list[RSSEntry]:
    """Parse an RSS 2.0 or Atom 1.0 feed body into entries.

    Raises :class:`xml.etree.ElementTree.ParseError` on malformed XML.
    """
    root = ET.fromstring(body)
    tag = root.tag.lower()
    if tag.endswith("rss") or tag == "rss":
        return _parse_rss(root)
    if tag.endswith("feed"):
        return _parse_atom(root)
    # Some servers return <rdf:RDF> for RSS 1.0; treat children
    # like RSS items.
    return _parse_rss(root)


def _text(elem, child_tag: str) -> str:
    found = elem.find(child_tag)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _parse_rss(root) -> list[RSSEntry]:
    entries: list[RSSEntry] = []
    # RSS 2.0: rss/channel/item ; RSS 1.0 / RDF: item directly under root
    items = root.findall(".//item")
    for item in items:
        title = _text(item, "title")
        link = _text(item, "link")
        summary = _text(item, "description")
        pub = _text(item, "pubDate") or _text(item, "{http://purl.org/dc/elements/1.1/}date")
        entries.append(
            RSSEntry(
                title=title,
                link=link,
                summary=summary,
                published_at=parse_rss_datetime(pub),
            )
        )
    return entries


def _parse_atom(root) -> list[RSSEntry]:
    entries: list[RSSEntry] = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        title_el = entry.find(f"{ATOM_NS}title")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = ""
        link_el = entry.find(f"{ATOM_NS}link")
        if link_el is not None:
            link = link_el.attrib.get("href", "") or (link_el.text or "").strip()
        summary_el = entry.find(f"{ATOM_NS}summary")
        if summary_el is None:
            summary_el = entry.find(f"{ATOM_NS}content")
        summary = (summary_el.text or "").strip() if summary_el is not None else ""
        published_el = entry.find(f"{ATOM_NS}published")
        if published_el is None:
            published_el = entry.find(f"{ATOM_NS}updated")
        pub_text = (published_el.text or "").strip() if published_el is not None else ""
        entries.append(
            RSSEntry(
                title=title,
                link=link,
                summary=summary,
                published_at=parse_rss_datetime(pub_text),
            )
        )
    return entries
