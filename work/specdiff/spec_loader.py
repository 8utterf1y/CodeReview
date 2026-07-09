from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from .models import Requirement


TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".adoc", ".html", ".htm"}


BUILTIN_RFC_REQUIREMENTS = [
    Requirement(
        id="RFC4861-ND-OPTIONS",
        document="RFC 4861",
        section="4.6.2 / 6.3.4",
        quote=(
            "RFC 4861 processes Neighbor Discovery options per received option, including "
            "Prefix Information options in Router Advertisements. A receiver-side arbitrary "
            "count cap can discard otherwise valid options."
        ),
        normalized="Process valid Neighbor Discovery options without an arbitrary small count limit.",
        keywords=["neighbor", "discovery", "option", "prefix", "nd6", "ndopt"],
        source="builtin-rfc-hint",
    ),
    Requirement(
        id="RFC4861-PROXY-NA-DELAY",
        document="RFC 4861",
        section="7.2.8 / 10",
        quote=(
            "RFC 4861 proxy/anycast Neighbor Advertisement handling uses a random response "
            "delay bounded by MAX_ANYCAST_DELAY_TIME to reduce response collisions."
        ),
        normalized="Proxy Neighbor Advertisements should be randomly delayed before transmission.",
        keywords=["proxy", "neighbor", "advertisement", "delay", "random", "anycast"],
        source="builtin-rfc-hint",
    ),
    Requirement(
        id="RFC4861-PROXY-UNSOLICITED-NA",
        document="RFC 4861",
        section="7.2.8",
        quote=(
            "RFC 4861 proxy Neighbor Advertisement behavior includes proactively updating "
            "neighbors when proxy state changes; absence of an unsolicited/all-nodes NA path "
            "leaves neighbor caches stale."
        ),
        normalized="Proxy implementations should support unsolicited Neighbor Advertisements.",
        keywords=["proxy", "unsolicited", "neighbor", "advertisement"],
        source="builtin-rfc-hint",
    ),
    Requirement(
        id="RFC8200-EXTENSION-HEADER-CHAIN",
        document="RFC 8200",
        section="4 / 4.5",
        quote=(
            "RFC 8200 encodes IPv6 extension headers as a Next Header chain. Fragment "
            "header handling must account for preceding extension headers rather than "
            "checking only the IPv6 base header's immediate Next Header value."
        ),
        normalized="IPv6 fragmentation logic must walk the extension-header chain to find a Fragment header.",
        keywords=["ipv6", "extension", "fragment", "next header", "chain"],
        source="builtin-rfc-hint",
    ),
    Requirement(
        id="RFC8415-DHCPV6",
        document="RFC 8415",
        section="all",
        quote=(
            "RFC 8415 defines DHCPv6 client/server message processing for IPv6 address "
            "assignment and configuration parameters; a compliant implementation needs "
            "discoverable DHCPv6 protocol entry points."
        ),
        normalized="An IPv6 stack claiming DHCPv6 support needs implementation entry points for DHCPv6.",
        keywords=["dhcpv6", "dhcp6"],
        source="builtin-rfc-hint",
    ),
    Requirement(
        id="RFC2710-MLD",
        document="RFC 2710",
        section="all",
        quote=(
            "RFC 2710 defines Multicast Listener Discovery as ICMPv6 multicast listener "
            "messages. The receive path must deliver those packets to IPv6/ICMPv6 MLD handling."
        ),
        normalized="MLD ICMPv6 multicast messages must be received and dispatched to the IPv6 stack.",
        keywords=["mld", "multicast", "icmpv6", "listener"],
        source="builtin-rfc-hint",
    ),
]


def load_spec_texts(path: Path) -> List[tuple[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"docs path does not exist: {path}")

    files: Iterable[Path]
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
    else:
        files = [path]

    texts: List[tuple[str, str]] = []
    for file in files:
        if file.suffix.lower() not in TEXT_SUFFIXES and path.is_dir():
            continue
        try:
            texts.append((str(file), file.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return texts


def extract_requirements(path: Path) -> List[Requirement]:
    texts = load_spec_texts(path)
    requirements: List[Requirement] = []
    counter = 1
    for name, text in texts:
        current_section = ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            header = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if header:
                current_section = header.group(2).strip()
            if re.search(r"\b(MUST|MUST NOT|SHOULD|SHOULD NOT|REQUIRED|SHALL)\b", stripped, re.I):
                requirements.append(
                    Requirement(
                        id=f"DOC-{counter:04d}",
                        document=name,
                        section=current_section or "unknown",
                        quote=stripped[:600],
                        normalized=stripped[:600],
                        keywords=_keywords(stripped),
                    )
                )
                counter += 1

    corpus = "\n".join(text for _, text in texts).lower()
    for req in BUILTIN_RFC_REQUIREMENTS:
        rfc_name = req.document.lower().replace(" ", "")
        spaced = req.document.lower()
        if rfc_name in corpus.replace(" ", "") or spaced in corpus or any(k in corpus for k in req.keywords):
            requirements.append(req)

    if not requirements:
        requirements.extend(BUILTIN_RFC_REQUIREMENTS)
    return requirements


def find_requirement(requirements: List[Requirement], req_id: str) -> Requirement:
    for req in requirements:
        if req.id == req_id:
            return req
    for req in BUILTIN_RFC_REQUIREMENTS:
        if req.id == req_id:
            return req
    raise KeyError(req_id)


def _keywords(text: str) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    stop = {"the", "and", "that", "with", "shall", "must", "should", "not", "for", "from"}
    return sorted({word for word in words if word not in stop})[:20]
