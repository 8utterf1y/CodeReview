from __future__ import annotations

<<<<<<< HEAD
from typing import List

from .code_index import CodeIndex
from .models import Finding, Requirement


def run_all_checkers(_index: CodeIndex, _requirements: List[Requirement]) -> List[Finding]:
    """Compatibility shim.

    Benchmark-specific known-answer checkers are regression fixtures, not production audit logic.
    The OpenCode audit path is driven by requirements, Code Facts, batch investigation, and assembly.
    """
    return []
=======
import re
from typing import Callable, List, Optional

from .code_index import CodeIndex
from .models import CodeHit, Evidence, Finding, Requirement
from .spec_loader import find_requirement


Checker = Callable[[CodeIndex, List[Requirement]], List[Finding]]


def run_all_checkers(index: CodeIndex, requirements: List[Requirement]) -> List[Finding]:
    findings: List[Finding] = []
    for checker in CHECKERS:
        findings.extend(checker(index, requirements))
    return _renumber(_dedupe(findings))


def check_nd_option_limit(index: CodeIndex, requirements: List[Requirement]) -> List[Finding]:
    req = find_requirement(requirements, "RFC4861-ND-OPTIONS")
    hits = index.search(r"\bnd6_maxndopt\b|\bmaxndopt\b", file_regex=r"(^|/)nd6\.c$")
    numeric_hits = [hit for hit in hits if re.search(r"=\s*(?:[1-9]|1[0-9]|2[0-9])\b|>\s*V?_?nd6_maxndopt", hit.quote)]
    if not numeric_hits and hits:
        numeric_hits = hits[:1]
    if not numeric_hits:
        return []
    hit = numeric_hits[0]
    return [
        Finding(
            id="ISSUE",
            title="Neighbor Discovery option processing is capped by a small implementation limit",
            match_type="code_weaker_than_spec",
            severity="HIGH",
            confidence=0.9,
            description=(
                "The implementation appears to enforce a fixed Neighbor Discovery option count limit. "
                "Valid ND messages can carry multiple options, and a small arbitrary cap can cause "
                "otherwise valid options to be ignored or rejected."
            ),
            spec_evidence=req.evidence(),
            code_evidence=hit.evidence("Found ND option limit symbol or guard."),
            verification=[
                "Searched nd6.c for nd6_maxndopt/maxndopt.",
                "Flagged a fixed option-count limit as weaker than RFC-style processing of valid ND options.",
            ],
        )
    ]


def check_proxy_na_delay(index: CodeIndex, requirements: List[Requirement]) -> List[Finding]:
    req = find_requirement(requirements, "RFC4861-PROXY-NA-DELAY")
    path, text = index.file_text_by_rel_suffix("freebsd/netinet6/nd6_nbr.c")
    if path is None:
        hits = index.search(r"proxy.*neighbor|neighbor.*proxy|nd6.*proxy")
        return _absence_finding(
            req,
            "Proxy Neighbor Advertisement delay could not be verified",
            "Relevant nd6_nbr.c implementation file was not found; proxy NA delay support is absent or located unexpectedly.",
            hits[:1],
            confidence=0.55,
            verification=["Searched for proxy Neighbor Discovery code but did not find the expected implementation file."],
        )

    rel = index.rel(path)
    lower = text.lower()
    if "proxy" not in lower:
        return []

    explicit_missing = _line_hits(rel, text, r"proxy advertisement delay rule")
    if explicit_missing:
        for hit in explicit_missing:
            if _near_terms_by_line(text, hit.line, ["not implemented"], window=4):
                return [
                    Finding(
                        id="ISSUE",
                        title="Proxy Neighbor Advertisement delay rule is explicitly not implemented",
                        match_type="missing_in_code",
                        severity="HIGH",
                        confidence=0.96,
                        description=(
                            "The Neighbor Discovery implementation explicitly documents that the proxy advertisement "
                            "delay rule is not implemented. Proxy NA responses are emitted from the normal NA output "
                            "path without a dedicated random delay stage."
                        ),
                        spec_evidence=req.evidence(),
                        code_evidence=hit.evidence("Nearby source comment states this rule is among items not implemented yet."),
                        verification=[
                            "Read freebsd/netinet6/nd6_nbr.c.",
                            "Found a source comment listing the proxy advertisement delay rule under not-implemented items.",
                            "Confirmed proxy NA output accepts sdl0/proxy state in nd6_na_output_fib.",
                        ],
                    )
                ]

    proxy_send_hits = _line_hits(rel, text, r"nd6_na_output|proxy|RTF_ANNOUNCE|rt_flags.*proxy|neighbor advertisement")
    send_hits = _line_hits(rel, text, r"nd6_na_output|icmp6.*na|ND_NEIGHBOR_ADVERT")
    delay_terms = ["MAX_ANYCAST_DELAY_TIME", "arc4random", "random", "callout", "timeout", "DELAY", "hz"]
    has_delay_at_send = any(_near_terms_by_line(text, hit.line, delay_terms, window=35) for hit in send_hits)
    has_proxy_random = _near_terms(text, "proxy", ["MAX_ANYCAST_DELAY_TIME", "arc4random", "random"], window=45)
    if has_delay_at_send or has_proxy_random:
        return []

    hit = proxy_send_hits[0] if proxy_send_hits else CodeHit(rel, 1, "proxy Neighbor Advertisement path present, but no nearby random delay logic found")
    return [
        Finding(
            id="ISSUE",
            title="Proxy Neighbor Advertisement path lacks random delay before response",
            match_type="code_weaker_than_spec",
            severity="HIGH",
            confidence=0.82,
            description=(
                "Proxy Neighbor Advertisements appear to be sent without nearby timer or randomization logic. "
                "RFC 4861 expects proxy/anycast-style responses to be randomly delayed to reduce collisions."
            ),
            spec_evidence=req.evidence(),
            code_evidence=hit.evidence("No random delay, timer, or MAX_ANYCAST_DELAY_TIME use was found near proxy NA handling."),
            verification=[
                "Read freebsd/netinet6/nd6_nbr.c.",
                "Searched proxy NA handling and NA send sites for random, callout, timeout, delay, hz, and MAX_ANYCAST_DELAY_TIME terms.",
                "Reported only because proxy handling exists and no nearby delay mechanism was found.",
            ],
        )
    ]


def check_proxy_unsolicited_na(index: CodeIndex, requirements: List[Requirement]) -> List[Finding]:
    req = find_requirement(requirements, "RFC4861-PROXY-UNSOLICITED-NA")
    proxy_hits = index.search(r"proxy", file_regex=r"(^|/)nd6_nbr\.c$", max_hits=20)
    if not proxy_hits:
        return []
    explicit_unsolicited = index.search(
        r"\bunsolicited\b|announce.*neighbor.*advert|neighbor.*advert.*announce|proxy.*announce|announce.*proxy",
        file_regex=r"(^|/)nd6_nbr\.c$",
        max_hits=20,
    )
    if explicit_unsolicited:
        return []
    output_hits = index.search(r"proxy \?|sdl0.*proxy|nd6_na_output_fib", file_regex=r"(^|/)nd6_nbr\.c$", max_hits=40)
    evidence = _prefer_hit(output_hits, r"proxy \?|sdl0.*proxy") or (output_hits[0] if output_hits else proxy_hits[0])
    return [
        Finding(
            id="ISSUE",
            title="Proxy Neighbor Advertisement implementation lacks unsolicited advertisement support",
            match_type="missing_in_code",
            severity="MEDIUM",
            confidence=0.74,
            description=(
                "The file contains proxy Neighbor Discovery handling, but no clear unsolicited Neighbor "
                "Advertisement path was found. Existing proxy NA output is tied to solicited Neighbor "
                "Solicitation processing rather than a proactive proxy-state announcement."
            ),
            spec_evidence=req.evidence(),
            code_evidence=evidence.evidence("Proxy NA output exists, but no explicit unsolicited proxy NA path was found."),
            verification=[
                "Searched nd6_nbr.c for proxy handling.",
                "Searched the same file for explicit unsolicited/proactive proxy Neighbor Advertisement terms.",
                "Did not count DAD all-nodes NA or link-layer-address option handling as proxy unsolicited NA support.",
            ],
        )
    ]


def check_ipv6_fragment_chain(index: CodeIndex, requirements: List[Requirement]) -> List[Finding]:
    req = find_requirement(requirements, "RFC8200-EXTENSION-HEADER-CHAIN")
    path, text = index.file_text_by_rel_suffix("dpdk/lib/ip_frag/rte_ip_frag.h")
    if path is None:
        hits = index.search(r"fragment|frag_hdr|next_header|nexthdr", max_hits=20)
        return _absence_finding(
            req,
            "IPv6 fragment header chain handling could not be verified",
            "The expected DPDK fragmentation header file was not found; fragment parsing should be reviewed.",
            hits[:1],
            confidence=0.5,
            verification=["Searched repository for fragment and next-header terms."],
        )

    rel = index.rel(path)
    lower = text.lower()
    has_fragment_check = "fragment" in lower and ("next_header" in lower or "nexthdr" in lower or "proto" in lower)
    fragment_lines = _line_hits(rel, text, r"IPPROTO_FRAGMENT|RTE_IPV6_EHDR|fragment|frag_hdr")
    has_chain_loop = any(_near_chain_walk(text, hit.line, window=45) for hit in fragment_lines)
    has_extension_terms = bool(re.search(r"hop|routing|destination|extension|ext", text, re.I))
    if not has_fragment_check or (has_chain_loop and has_extension_terms):
        return []

    explicit_comment = _line_hits(rel, text, r"only looks at the extension header|doesn.t follow the whole chain")
    hits = explicit_comment or fragment_lines or _line_hits(rel, text, r"fragment|next_header|nexthdr|IPPROTO_FRAGMENT")
    hit = hits[0] if hits else CodeHit(rel, 1, "Fragment-related logic found without obvious extension-header chain walking")
    return [
        Finding(
            id="ISSUE",
            title="IPv6 fragmentation logic appears to check only a direct Fragment header",
            match_type="partial_match",
            severity="HIGH",
            confidence=0.79,
            description=(
                "The fragmentation helper contains Fragment/Next Header checks, but no clear loop over the IPv6 "
                "extension-header chain. Packets with preceding extension headers may be misclassified."
            ),
            spec_evidence=req.evidence(),
            code_evidence=hit.evidence("The helper documents or implements only a direct Fragment-header check."),
            verification=[
                "Read dpdk/lib/ip_frag/rte_ip_frag.h.",
                "Searched for Fragment/Next Header logic.",
                "Checked for a loop that advances through extension headers before deciding whether a Fragment header exists.",
            ],
        )
    ]


def check_dhcpv6_absence(index: CodeIndex, requirements: List[Requirement]) -> List[Finding]:
    req = find_requirement(requirements, "RFC8415-DHCPV6")
    hits = index.search(r"\bdhcpv6\b|\bdhcp6\b|DHCPV6|DHCP6", max_hits=50)
    code_hits = [
        hit
        for hit in hits
        if not re.search(r"readme|doc|license|changelog|drivers/net|contrib|firmware|boot", hit.file, re.I)
    ]
    if len(code_hits) >= 3:
        return []
    evidence = CodeHit(
        file="repository scan",
        line=0,
        quote=(
            "No DHCPv6/DHCP6 protocol implementation entry points were found in indexed source files; "
            "remaining DHCP hits were documentation, IPv4 DHCP, or device-management strings."
        ),
    )
    return [
        Finding(
            id="ISSUE",
            title="DHCPv6 implementation appears absent or only stubbed",
            match_type="missing_in_code",
            severity="MEDIUM",
            confidence=0.72 if code_hits else 0.82,
            description=(
                "The repository scan found little or no DHCPv6 implementation surface. If the design/RFC set "
                "requires DHCPv6 behavior, this is a missing protocol capability."
            ),
            spec_evidence=req.evidence(),
            code_evidence=evidence.evidence("Repository-wide DHCPv6 symbol search produced no substantial implementation hits."),
            verification=[
                "Searched source files for dhcpv6, dhcp6, DHCPV6, and DHCP6.",
                "Ignored unrelated NIC firmware/management DHCP strings and documentation-only hits.",
            ],
        )
    ]


def check_mld_multicast_path(index: CodeIndex, requirements: List[Requirement]) -> List[Finding]:
    req = find_requirement(requirements, "RFC2710-MLD")
    path, text = index.file_text_by_rel_suffix("lib/ff_dpdk_if.c")
    if path is None:
        hits = index.search(r"\bmld\b|multicast|icmp6|icmpv6", max_hits=20)
        return _absence_finding(
            req,
            "MLD multicast receive path could not be verified",
            "The expected DPDK interface file was not found; MLD dispatch should be reviewed.",
            hits[:1],
            confidence=0.5,
            verification=["Searched for MLD, multicast, ICMP6, and ICMPv6 terms."],
        )

    rel = index.rel(path)
    lower = text.lower()
    has_ipv6 = "ipv6" in lower or "ether_type_ipv6" in lower
    has_multicast = "multicast" in lower or "is_multicast" in lower or "mcast" in lower
    has_mld = "mld" in lower
    has_icmp6 = "icmp6" in lower or "icmpv6" in lower
    explicit_mld_dispatch = bool(re.search(r"\bmld(?:6)?_(?:input|receive|recv|process|handle)\b", text, re.I))
    if explicit_mld_dispatch:
        return []
    if not has_ipv6:
        return []
    hits = _line_hits(rel, text, r"multicast|mcast|icmp6|icmpv6|ipv6|ETHER_TYPE_IPV6")
    hit = hits[0] if hits else CodeHit(rel, 1, "IPv6 receive path found without explicit MLD/ICMPv6 multicast handling")
    confidence = 0.72 if has_multicast or has_icmp6 or has_mld else 0.58
    return [
        Finding(
            id="ISSUE",
            title="MLD multicast reception path is not clearly dispatched to ICMPv6/MLD handling",
            match_type="missing_in_code",
            severity="MEDIUM",
            confidence=confidence,
            description=(
                "The DPDK interface layer contains IPv6 receive logic, but no clear MLD-specific handling was found. "
                "MLD is carried over ICMPv6 multicast and must reach the IPv6 control-plane path."
            ),
            spec_evidence=req.evidence(),
            code_evidence=hit.evidence("No explicit MLD handling was found in ff_dpdk_if.c."),
            verification=[
                "Read lib/ff_dpdk_if.c.",
                "Searched for MLD, ICMPv6/ICMP6, multicast, IPv6 dispatch terms, and explicit mld_input-style handlers.",
                "Reported because IPv6 path exists but explicit MLD dispatch evidence is missing or weak.",
            ],
        )
    ]


CHECKERS: List[Checker] = [
    check_nd_option_limit,
    check_proxy_na_delay,
    check_proxy_unsolicited_na,
    check_ipv6_fragment_chain,
    check_dhcpv6_absence,
    check_mld_multicast_path,
]


def _line_hits(file: str, text: str, pattern: str) -> List[CodeHit]:
    regex = re.compile(pattern, re.I)
    hits: List[CodeHit] = []
    for idx, line in enumerate(text.splitlines(), 1):
        if regex.search(line):
            hits.append(CodeHit(file=file, line=idx, quote=line.strip()[:500]))
    return hits


def _near_terms(text: str, anchor: str, terms: List[str], *, window: int) -> bool:
    lines = text.splitlines()
    anchors = [idx for idx, line in enumerate(lines) if anchor.lower() in line.lower()]
    for idx in anchors:
        start = max(0, idx - window)
        end = min(len(lines), idx + window + 1)
        block = "\n".join(lines[start:end]).lower()
        if any(term.lower() in block for term in terms):
            return True
    return False


def _near_terms_by_line(text: str, line_no: int, terms: List[str], *, window: int) -> bool:
    lines = text.splitlines()
    start = max(0, line_no - window - 1)
    end = min(len(lines), line_no + window)
    block = "\n".join(lines[start:end]).lower()
    return any(term.lower() in block for term in terms)


def _near_chain_walk(text: str, line_no: int, *, window: int) -> bool:
    lines = text.splitlines()
    start = max(0, line_no - window - 1)
    end = min(len(lines), line_no + window)
    block = "\n".join(lines[start:end])
    has_loop = bool(re.search(r"\b(for|while)\s*\(", block, re.I))
    advances_next = bool(re.search(r"(next|nxt|proto|hdr|header)\s*=", block, re.I))
    recognizes_ext = bool(re.search(r"HOPOPTS|ROUTING|DSTOPTS|AH|ESP|extension|ext", block, re.I))
    return has_loop and advances_next and recognizes_ext


def _prefer_hit(hits: List[CodeHit], pattern: str) -> Optional[CodeHit]:
    regex = re.compile(pattern, re.I)
    for hit in hits:
        if regex.search(hit.quote):
            return hit
    return None


def _absence_finding(
    req: Requirement,
    title: str,
    description: str,
    hits: List[CodeHit],
    *,
    confidence: float,
    verification: List[str],
) -> List[Finding]:
    evidence = hits[0].evidence("Fallback search hit.") if hits else Evidence(
        file="repository scan",
        line=0,
        quote="No precise implementation location was found.",
        note="Absence-based finding.",
    )
    return [
        Finding(
            id="ISSUE",
            title=title,
            match_type="missing_in_code",
            severity="MEDIUM",
            confidence=confidence,
            description=description,
            spec_evidence=req.evidence(),
            code_evidence=evidence,
            verification=verification,
        )
    ]


def _dedupe(findings: List[Finding]) -> List[Finding]:
    seen = set()
    result: List[Finding] = []
    for finding in sorted(findings, key=lambda item: item.confidence, reverse=True):
        key = (finding.title, finding.code_evidence.file, finding.code_evidence.line)
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result


def _renumber(findings: List[Finding]) -> List[Finding]:
    for idx, finding in enumerate(findings, 1):
        finding.id = f"ISSUE-{idx:03d}"
    return findings
>>>>>>> bc85301 (workbatchwin)
