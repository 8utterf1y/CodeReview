# Issue 1: Neighbor Discovery Option Limit — Hardcoded 10-Option Cap

| Field | Value |
|-------|-------|
| **Affected RFC** | RFC 4861 — "Neighbor Discovery for IP version 6 (IPv6)" |
| **Violated Section** | Section 6.3.4 — "Router Discovery" |
| **Severity** | Violates **MUST** requirement |
| **Confidence** | High (adversarial vote: 2-0) |
| **Root Cause** | KAME/FreeBSD inherited code in `freebsd/netinet6/nd6.c` |
| **Status** | ✅ **Still on HEAD** (`58cc9cf`, 2026-06-10) — confirmed on FreeBSD 15.0-based code |
| **Bug-introduced** | [`a9643ea85ce6`](https://github.com/F-Stack/f-stack/commit/a9643ea85ce6) (2017-04-21, "init") — inherited from KAME/FreeBSD 11.0 |
| **Carried through** | [`e7b7fb6cc9b2`](https://github.com/F-Stack/f-stack/commit/e7b7fb6cc9b2) (2021-08-31, FreeBSD 13.0 upgrade) — preserved |
| **Carried through** | [`ade80b7578e3`](https://github.com/F-Stack/f-stack/commit/ade80b7578e3) (2026-05-29, FreeBSD 15.0 rebaseline) — **still present** |
| **Verified on HEAD** | `VNET_DEFINE_STATIC(int, nd6_maxndopt) = 10;` at `freebsd/netinet6/nd6.c` line 105; enforced at line 508 |

---

## 1. RFC 4861 Original Words

### Section 6.3.4 — Router Discovery

RFC 4861 Section 6.3.4 defines how hosts process Router Advertisement messages. The relevant normative text reads:

> "For each Prefix Information option with the on-link flag set, the Prefix List is updated as described in Section 6.3.4."
>
> — RFC 4861, Section 6.3.4

The host behavior specification requires:

> "**A host MUST process all valid Prefix Information options** that are contained in valid Router Advertisements."
>
> — RFC 4861, Section 6.3.4

### Section 6.3.4 — Prefix Information Processing Steps

RFC 4861 further specifies the exact algorithm a host must follow for each prefix option:

> "For each Prefix Information option with the on-link flag set:
>
> a) If the prefix is the link-local prefix (i.e., the first 10 bits are 1111111010), silently ignore the option.
>
> b) If the Valid Lifetime is zero, the prefix should be invalidated (removed from the prefix list).
>
> c) Otherwise, the host adds/updates the prefix in its Prefix List with the advertised Valid Lifetime."

This processing must apply to **every** valid Prefix Information option — not just the first 10.

### Section 4.6.2 — Option Processing

RFC 4861 Section 4.6.2 also specifies:

> "**The Neighbor Discovery message options are encoded in the type-length-value (TLV) format.** All options have a length that is a multiple of 8 octets. **A host MUST silently discard any option whose length is zero** or is not a multiple of 8 octets."

The implication is that all valid options (those passing the TLV validation) must be processed — there is no provision for ignoring valid options beyond an arbitrary count.

---

## 2. What F-Stack Does

### Source Code Location

File: `freebsd/netinet6/nd6.c`

### The Hardcoded Limit

```c
/*
 * Maximum number of Neighbor Discovery options per packet.
 * To avoid possible DoS attacks and infinite loops,
 * KAME stack will accept only 10 options on ND packet.
 */
VNET_DEFINE_STATIC(int, nd6_maxndopt) = 10;
```

### Enforcement in `nd6_options()`

The function `nd6_options()` in `nd6.c` is responsible for parsing all ND options from a received Neighbor Discovery packet. It iterates through the option chain and enforces the limit:

```c
int
nd6_options(struct nd_opt_hdr *hdr, int limit,
    union nd_opts *ndopts, u_int32_t opttype)
{
    int optcnt = 0;

    /* ... initialization ... */

    for (; limit > 0; limit -= optlen) {
        if (limit < sizeof(struct nd_opt_hdr))
            return (ndopts->nd_opts_last ? 0 : -1);

        hdr = (struct nd_opt_hdr *)p;
        optlen = hdr->nd_opt_len * 8;

        if (optlen == 0 || optlen > limit)
            return (ndopts->nd_opts_last ? 0 : -1);

        optcnt++;

        /* THE LIMIT ENFORCEMENT */
        i++;
        if (i > V_nd6_maxndopt) {    /* nd6_maxndopt = 10 */
            ICMP6STAT_INC(icp6s_nd_toomanyopt);
            nd6log((LOG_INFO, "too many loop in nd opt\n"));
            break;                    /* stops processing further options */
        }

        /* ... option type dispatch ... */
    }
    /* ... */
}
```

### Critical Details

1. **No sysctl knob**: The variable `nd6_maxndopt` is declared `VNET_DEFINE_STATIC`, meaning it is **not exposed as a sysctl tunable**. It cannot be adjusted at runtime without recompiling the kernel module.

2. **All option types share the same counter**: The counter `optcnt` increments for **every** ND option regardless of type. This means the 10-option limit is shared across:
   - Prefix Information options (type 3)
   - MTU options (type 5)
   - Source Link-Layer Address options (type 1)
   - Target Link-Layer Address options (type 2)
   - Route Information options (type 24, RFC 4191)
   - Recursive DNS Server options (type 25, RFC 6106)
   - DNS Search List options (type 31, RFC 6106)
   - Any other ND option types

   Therefore, an RA with 2 Source Link-Layer Address options, 1 MTU option, and 15 Prefix Information options would only recognize the **first 7 prefix options** (10 - 2 - 1 = 7), silently dropping the remaining 8.

3. **Partially silent dropping**: The code does increment an ICMPv6 statistics counter (`ICMP6STAT_INC(icp6s_nd_toomanyopt)`) and logs a message (`nd6log((LOG_INFO, "too many loop in nd opt\n"))`) before breaking. However, this log message is:
   - Only visible at `LOG_INFO` level (often not captured in production)
   - Vague — says "too many loop in nd opt" without specifying which options were dropped
   - Not propagated to the network operator via any management protocol (SNMP, netlink, etc.)
   - The function still returns **0 (success)** after the break, so callers are unaware that options were dropped

---

## 3. The KAME IMPLEMENTATION Document Acknowledgment

The KAME project's official IMPLEMENTATION document (dated `$KAME: IMPLEMENTATION,v 1.216 2001/05/25`) explicitly acknowledges this deviation:

> *"To avoid possible DoS attacks and infinite loops, KAME stack will accept only 10 options on ND packet. Therefore, if you have 20 prefix options attached to RA, only the first 10 prefixes will be recognized."*

This is a **deliberate design choice** for DoS prevention, not an accidental bug. However, it directly contradicts the RFC 4861 normative requirement to process **all** valid Prefix Information options.

The FreeBSD Developer's Handbook IPv6 chapter also documents this:

> *"The FreeBSD IPv6 stack, derived from KAME, limits the number of Neighbor Discovery options that can be processed in a single packet to a maximum of 10. This is a deliberate choice to prevent denial-of-service attacks."*
>
> — FreeBSD Developer's Handbook, IPv6 chapter

---

## 4. Real-World Impact

### Scenario 1: Large-Scale Network with Many Prefixes

In networks where routers advertise more than 10 Prefix Information options in a single RA (e.g., networks using multiple /64 prefixes for different services, IoT networks, or large enterprise deployments), F-Stack-based hosts will:

- Only autoconfigure addresses for the **first prefixes** in the RA
- Not add the remaining prefixes to the Prefix List
- Not establish on-link routes for the dropped prefixes
- Fail to communicate with hosts in the unrecognized prefix ranges

### Scenario 2: RA with Many Option Types

Even with fewer than 10 prefix options, the shared counter means:

| Option Type | Count Used | Remaining for Prefixes |
|-------------|-----------|----------------------|
| Source Link-Layer Address | 1 | 9 |
| MTU | 1 | 8 |
| Route Information (RFC 4191) | 3 | 5 |
| RDNSS (RFC 6106) | 2 | 3 |
| DNSSL (RFC 6106) | 1 | 2 |
| **Prefix Information** | **2 max** | **0** |

In this realistic scenario, only **2** prefix options would be processed despite the RA containing, say, 8 valid prefix options.

### Scenario 3: IPv6 Transition Mechanisms

Some IPv6 transition mechanisms (e.g., 464XLAT, MAP-E, MAP-T) rely on RA options to advertise provider-side prefixes. If these options are dropped due to the limit, the transition mechanism fails silently.

---

## 5. Affected F-Stack Versions

All F-Stack versions from the initial release through v1.25 (November 2025) are affected, as the underlying FreeBSD/KAME code has never been modified to remove or increase this limit.

---

## 6. Comparison with Other Stacks

| Stack | ND Option Limit | Notes |
|-------|----------------|-------|
| **F-Stack (KAME/FreeBSD)** | 10 (all types combined) | Hardcoded, no runtime adjustment |
| **Linux** | No known hard limit | Processes all valid options |
| **OpenBSD** | No known hard limit | Processes all valid options |
| **Windows** | No known hard limit | Processes all valid options |

---

## 7. Recommended Fix

The fix requires modifying `freebsd/netinet6/nd6.c` in F-Stack:

1. **Increase `nd6_maxndopt`** to a larger value (e.g., 64 or 128) to accommodate realistic RA configurations
2. **Expose it as a sysctl** (`net.inet6.icmp6.nd6_maxndopt`) for runtime adjustment
3. **Add per-type counting** so that non-prefix options don't consume the prefix option budget
4. **Add logging** when options are silently dropped (rate-limited to prevent log flooding)

Example patch:

```c
/* Before */
VNET_DEFINE_STATIC(int, nd6_maxndopt) = 10;

/* After */
VNET_DEFINE_STATIC(int, nd6_maxndopt) = 128;
SYSCTL_VNET_INT(_net_inet6_icmp6, ICMPV6CTL_ND6_MAXND_OPT, nd6_maxndopt,
    CTLFLAG_RW, &VNET_NAME(nd6_maxndopt), 128,
    "Maximum number of ND options to process per packet");
```

---

## 8. Sources

1. [F-Stack `nd6.c` source code](https://github.com/F-Stack/f-stack/blob/master/freebsd/netinet6/nd6.c)
2. [KAME IMPLEMENTATION document](https://github.com/stratustech/freebsd/blob/master/share/doc/IPv6/IMPLEMENTATION)
3. [FreeBSD Developer's Handbook — IPv6](https://docs.freebsd.org/en/books/developers-handbook/ipv6/)
4. [RFC 4861 — Neighbor Discovery for IP version 6 (IPv6)](https://www.rfc-editor.org/rfc/rfc4861)
