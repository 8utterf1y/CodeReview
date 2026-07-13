from __future__ import annotations

from typing import List

from ..models import Requirement
from .base import RuleFamily, requirement_blob


RULE_FAMILIES: List[RuleFamily] = [
    RuleFamily(
        name="module_presence",
        description="Required service, module, protocol, endpoint, worker, CLI command, or feature surface exists and is enabled.",
        requirement_terms=("support", "module", "service", "protocol", "client", "server", "endpoint", "command", "feature"),
        strong_evidence=("entry registration", "build enablement", "reachable handler"),
        medium_evidence=("handler implementation", "configuration knob", "tests exercising entry"),
        weak_evidence=("constant", "type", "comment", "documentation hit", "string literal"),
        covered_requires="entry registration plus build enablement plus reachable handler, or two independent medium signals.",
    ),
    RuleFamily(
        name="parser_or_format",
        description="Parsers, encoders, schemas, protocol fields, TLVs, headers, lists, chains, and versioned formats.",
        requirement_terms=("parse", "parser", "format", "field", "header", "option", "schema", "tlv", "chain", "list", "decode", "encode"),
        strong_evidence=("field read/write", "length or bounds check", "loop or chain traversal", "unknown-field handling"),
        medium_evidence=("parser function", "switch over field/type", "serializer/deserializer"),
        weak_evidence=("struct", "macro", "enum", "constant", "comment"),
        covered_requires="format behavior evidence such as reads/checks/traversal; definitions alone are insufficient.",
    ),
    RuleFamily(
        name="dispatch_or_routing",
        description="Message routing, middleware/filter order, protocol dispatch, event buses, callback registration, and handler selection.",
        requirement_terms=("dispatch", "route", "handler", "filter", "message", "event", "packet", "callback", "queue", "topic"),
        strong_evidence=("entry path", "classifier", "handler call"),
        medium_evidence=("handler table", "callback registration", "switch/case routing"),
        weak_evidence=("handler definition", "message constant", "type declaration"),
        covered_requires="entry path to classifier to handler call; isolated handlers or constants are insufficient.",
    ),
    RuleFamily(
        name="state_machine",
        description="Explicit lifecycle or protocol states, transitions, terminal states, illegal states, and recovery behavior.",
        requirement_terms=("state", "transition", "lifecycle", "phase", "mode", "terminal", "retry", "recover"),
        strong_evidence=("state enum", "transition condition", "illegal/terminal state handling"),
        medium_evidence=("state switch", "state assignment", "transition tests"),
        weak_evidence=("enum only", "single assignment", "comment"),
        covered_requires="state model plus transition conditions; isolated enum or assignment is insufficient.",
    ),
    RuleFamily(
        name="timing_or_randomness",
        description="Timeouts, delays, backoff, retry windows, jitter, scheduling, rate limits, and idempotent timing behavior.",
        requirement_terms=("timeout", "delay", "random", "jitter", "backoff", "retry", "timer", "schedule", "rate"),
        strong_evidence=("timer/random/backoff API on target behavior path", "bounded retry policy"),
        medium_evidence=("timer setup", "random API use near behavior", "configurable timeout"),
        weak_evidence=("delay string", "random helper elsewhere", "comment"),
        covered_requires="timing/randomness evidence must be on the required behavior path, not merely present in the repo.",
    ),
    RuleFamily(
        name="config_behavior",
        description="Configuration options, defaults, feature flags, reload behavior, validation, and config-triggered side effects.",
        requirement_terms=("config", "configuration", "default", "flag", "option", "setting", "reload", "environment"),
        strong_evidence=("config parse", "default assignment", "validation", "runtime use or side effect"),
        medium_evidence=("config schema", "feature flag check", "documentation-to-key mapping"),
        weak_evidence=("key string", "comment", "sample config"),
        covered_requires="parse/default/validation must connect to runtime behavior.",
    ),
    RuleFamily(
        name="error_handling",
        description="Error returns, rollback, retries, fallback, alerts, failure isolation, and exceptional paths.",
        requirement_terms=("error", "fail", "failure", "rollback", "fallback", "exception", "retry", "abort", "recover"),
        strong_evidence=("error detection", "propagation/return", "cleanup or rollback"),
        medium_evidence=("error branch", "logging", "retry/fallback path"),
        weak_evidence=("error constant", "message string", "comment"),
        covered_requires="detected error must be handled on the relevant path; strings/constants alone are insufficient.",
    ),
    RuleFamily(
        name="security_property",
        description="Authentication, authorization, permissions, trust boundaries, validation, encryption, isolation, and rate limits.",
        requirement_terms=("auth", "permission", "authorize", "encrypt", "validate", "sanitize", "trust", "isolate", "secure", "rate limit"),
        strong_evidence=("check before sensitive action", "validated input used downstream", "deny path"),
        medium_evidence=("auth middleware", "validator registration", "policy mapping"),
        weak_evidence=("helper function only", "policy constant", "comment"),
        covered_requires="security check must dominate the sensitive action path.",
    ),
    RuleFamily(
        name="observability",
        description="Logs, metrics, counters, tracing, audit events, alerts, and operational visibility guarantees.",
        requirement_terms=("log", "metric", "counter", "trace", "audit", "alert", "observe", "telemetry"),
        strong_evidence=("event emission on target path", "metric/log includes required fields", "failure path instrumentation"),
        medium_evidence=("metric definition plus update", "logger call near behavior"),
        weak_evidence=("metric name only", "logger declaration", "comment"),
        covered_requires="observability event must be emitted on the required behavior path.",
    ),
    RuleFamily(
        name="resource_lifecycle",
        description="Initialization, open/acquire, cleanup/release, locks, connections, sessions, handles, and memory ownership.",
        requirement_terms=("init", "initialize", "open", "acquire", "release", "cleanup", "close", "lock", "unlock", "free", "session"),
        strong_evidence=("paired acquire/release", "cleanup on error path", "ownership transfer"),
        medium_evidence=("destructor/finalizer", "close path", "lock/unlock pair"),
        weak_evidence=("allocation only", "cleanup helper only", "comment"),
        covered_requires="lifecycle pair and failure cleanup must be connected to the same resource.",
    ),
    RuleFamily(
        name="compatibility_or_negotiation",
        description="Protocol versions, feature negotiation, capability discovery, fallback, and backward compatibility.",
        requirement_terms=("version", "compatible", "compatibility", "negotiate", "capability", "fallback", "upgrade", "downgrade"),
        strong_evidence=("capability discovery", "version branch", "fallback path"),
        medium_evidence=("version parser", "feature flag mapping", "compatibility tests"),
        weak_evidence=("version constant", "comment", "documentation hit"),
        covered_requires="negotiation decision must influence runtime behavior.",
    ),
    RuleFamily(
        name="data_consistency_or_mapping",
        description="Field mappings, enum/error-code mappings, schema-to-model mapping, config-to-runtime mapping, and persistence consistency.",
        requirement_terms=("map", "mapping", "field", "schema", "enum", "code", "translate", "convert", "persist", "consistency"),
        strong_evidence=("source field read", "target field write", "validation or exhaustiveness check"),
        medium_evidence=("mapping table", "converter function", "round-trip tests"),
        weak_evidence=("field names only", "struct definitions", "comment"),
        covered_requires="mapping must connect source and target semantics; matching names are insufficient.",
    ),
]

DEFAULT_FAMILY = RuleFamily(
    name="general_behavior",
    description="General functional behavior that does not fit a more specific rule family.",
    requirement_terms=(),
    strong_evidence=("entry behavior", "observable side effect", "test or assertion"),
    medium_evidence=("function implementation", "call site", "configuration connection"),
    weak_evidence=("symbol", "constant", "comment"),
    covered_requires="behavioral implementation evidence on a production path.",
)


def select_rule_family(requirement: Requirement) -> RuleFamily:
    blob = requirement_blob(requirement)
    scored = []
    for family in RULE_FAMILIES:
        score = sum(1 for term in family.requirement_terms if term in blob)
        scored.append((score, family))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else DEFAULT_FAMILY


def all_rule_families() -> List[RuleFamily]:
    return [*RULE_FAMILIES, DEFAULT_FAMILY]
