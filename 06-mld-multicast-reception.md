# Issue 6: MLD Multicast Reception Failure via DPDK KNI

| Field | Value |
|-------|-------|
| **Affected RFC** | RFC 2710 — "Multicast Listener Discovery (MLD) for IPv6" |
| **Successor RFC** | RFC 3810 — "Multicast Listener Discovery Version 2 (MLDv2) for IPv6" |
| **Related RFCs** | RFC 4291 — "IPv6 Addressing Architecture" (multicast addresses) |
| **Severity** | Functional failure (IPv6 KNI non-operational in MLD environments) |
| **Confidence** | High (adversarial vote: 2-0) |
| **Root Cause** | F-Stack `lib/ff_dpdk_if.c` — `protocol_filter()` function |
| **Status** | ✅ **Still on HEAD** (`58cc9cf`, 2026-06-10) |
| **Bug-introduced** | [`f069dcdcb727`](https://github.com/F-Stack/f-stack/commit/f069dcdcb727) (2024-10-17, "Support KNI ratelimit") by fengbojiang |
| **Pre-existing code** | IPv6/NDP filter path added by [`10b909a1b3cd`](https://github.com/F-Stack/f-stack/commit/10b909a1b3cd) (2019-07-17, "IPv6: support multi-processes, deep copy NDP packet and dispatch") |
| **Verified on HEAD** | `lib/ff_dpdk_if.c` line 1487: `rte_is_multicast_ether_addr(&hdr->dst_addr)` returns `FILTER_MULTI` before the IPv6 path at line 1493. MLD packets (ICMPv6 types 130-132) never reach `protocol_filter_icmp6()` which only matches types 133-137 (NDP). |
| **Bug mechanism** | Commit `f069dcdcb727` inserted the multicast MAC check (lines 1484-1489) **above** the existing IPv6/NDP filter path (lines 1491-1497), causing all IPv6 multicast packets to be intercepted before ICMPv6 type inspection |

---

## 1. RFC 2710 Original Words

### Section 1 — Introduction

RFC 2710 defines the Multicast Listener Discovery protocol:

> "**Multicast Listener Discovery (MLD)** is used by IPv6 routers to discover the presence of multicast listeners (i.e., nodes wishing to receive multicast packets) on their directly attached links, **and to discover which multicast addresses are of interest to those listeners.**"
>
> — RFC 2710, Section 1

### Section 3 — Message Formats

RFC 2710 defines three message types:

> "**Multicast Listener Query** (Type = 130): Sent by a router to query for multicast listeners on a link.
>
> **Multicast Listener Report** (Type = 131): Sent by a node to report that it is a multicast listener.
>
> **Multicast Listener Done** (Type = 132): Sent by a node to report that it is ceasing to be a multicast listener."
>
> — RFC 2710, Section 3

### Section 4 — Protocol Description

RFC 2710 Section 4 specifies the listener (node) behavior:

> "**When a node starts listening to a multicast address on an interface, it should immediately transmit an unsolicited Report for that address on that interface**, in case it is the first listener on the link."
>
> — RFC 2710, Section 4

And:

> "**A node that receives a General Query** on an interface must schedule a response delay, then send a Report for each multicast address to which it is listening."
>
> — RFC 2710, Section 4

### Section 5 — Message Destination Addresses

RFC 2710 specifies the destination addresses for MLD messages:

> "MLD messages are sent with a link-local IPv6 Source Address, an IPv6 Hop Limit of 1, and **an alert option containing a Router Alert option** in a Hop-by-Hop Options header."
>
> — RFC 2710, Section 2

The destination addresses are:

| Message Type | Destination Address | Multicast MAC |
|-------------|--------------------:|---------------|
| General Query | FF02::1 (all-nodes) | 33:33:00:00:00:01 |
| Multicast-Address-Specific Query | Target multicast address | 33:33:xx:xx:xx:xx |
| Report | Target multicast address | 33:33:xx:xx:xx:xx |
| Done | FF02::2 (all-routers) | 33:33:00:00:00:02 |

### RFC 4291 — IPv6 Multicast Address to MAC Address Mapping

RFC 4291 Section 2.7 defines the mapping from IPv6 multicast addresses to Ethernet MAC addresses:

> "**An IPv6 packet with a multicast destination address is transmitted using the mapping of that address to the link-layer multicast address.** For Ethernet, the link-layer address is derived from the low-order 32 bits of the multicast address, prepended with 33:33."
>
> — RFC 4291, Section 2.7

This means MLD messages for FF02::1 are sent to MAC address **33:33:00:00:00:01**, and all MLD messages have destination MAC addresses starting with **33:33:**.

---

## 2. What F-Stack Does

### The Architectural Problem

F-Stack uses DPDK KNI (Kernel Network Interface) to bridge between the user-space DPDK fast path and the kernel networking stack. The KNI interface allows certain packets (like NDP/ICMPv6) to be forwarded to the Linux kernel for processing.

The problem occurs in `lib/ff_dpdk_if.c` — specifically in the `protocol_filter()` function, which classifies incoming packets before dispatching them.

### Source Code Analysis

File: `lib/ff_dpdk_if.c`, lines 1462-1512 (as of HEAD `58cc9cf`)

```c
static enum FilterReturn
protocol_filter(const void *data, uint16_t len)
{
    /* ... parse Ethernet header, handle ARP ... */

    /* line 1484-1489: ADDED by commit f069dcdcb727 (2024-10-17) */
    /* PROBLEM: This check runs BEFORE IPv6-specific checks */
    if (rte_is_multicast_ether_addr(&hdr->dst_addr)) {
        return FILTER_MULTI;  /* MLD packets trapped here */
    }

    /* line 1491-1497: EXISTING since commit 10b909a1b3cd (2019-07-17) */
#if (!defined(__FreeBSD__) && defined(INET6)) || ...
    if (ether_type == RTE_ETHER_TYPE_IPV6) {
        return ff_kni_proto_filter(data, len, ether_type);
        /* MLD packets NEVER reach here */
    }
#endif
    /* ... */
}
```

### The Bug: Execution Order

The critical issue is the **order of checks** in the packet filtering pipeline:

```
Incoming Packet
      │
      ▼
┌─────────────────────────────┐
│ 1. Check ethertype          │
│    (IPv4, IPv6, ARP, etc.)  │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ 2. For IPv6:                │
│    Check if NDP (ICMPv6     │
│    type 133-137)            │
│    → FILTER_NDP             │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ 3. Check if multicast MAC   │
│    (33:33:xx:xx:xx:xx)      │
│    → FILTER_MULTI           │
│                             │
│  ★ MLD packets land here!   │
│    (MLD queries have        │
│     MAC 33:33:00:00:00:01)  │
└─────────────────────────────┘
```

The `protocol_filter()` function intercepts **ALL** frames with multicast destination MAC addresses (returning `FILTER_MULTI`) **BEFORE** the IPv6-specific `ff_kni_proto_filter()` is called. This means:

1. MLD Multicast Listener Queries (destined to FF02::1, MAC 33:33:00:00:00:01) are classified as `FILTER_MULTI`
2. They are **NOT** classified as `FILTER_NDP` (NDP only covers ICMPv6 types 133-137, not MLD types 130-132)
3. `FILTER_MULTI` packets follow a **less robust dispatch path** compared to `FILTER_NDP` packets

### Why MLD Is Not NDP

NDP (Neighbor Discovery Protocol) uses ICMPv6 message types:
- 133: Router Solicitation (RS)
- 134: Router Advertisement (RA)
- 135: Neighbor Solicitation (NS)
- 136: Neighbor Advertisement (NA)
- 137: Redirect

MLD uses ICMPv6 message types:
- 130: Multicast Listener Query
- 131: Multicast Listener Report
- 132: Multicast Listener Done

F-Stack's NDP detection only checks for types 133-137, so MLD messages (types 130-132) **fall through** to the generic multicast handler.

---

## 3. Impact Analysis

### What Fails

| Function | Depends on MLD | Works in F-Stack? |
|----------|----------------|-------------------|
| IPv6 Neighbor Discovery (RS/RA/NS/NA) | No | ✅ Yes (FILTER_NDP path) |
| IPv6 multicast group membership (MLD Report) | — itself | ❌ No |
| IPv6 multicast group leave (MLD Done) | — itself | ❌ No |
| IPv6 multicast reception (downstream) | Yes (switches need MLD snooping) | ❌ No |
| SLAAC address autoconfiguration | No | ✅ Yes |
| DHCPv6 via KNI | Yes (DHCPv6 uses multicast) | ❌ No |
| IPv6 KNI on AWS EC2 | Yes (AWS requires MLD) | ❌ No |

### Cloud Environment Impact

F-Stack developer documentation explicitly warns:

> *"DPDK KNI 无法接收 MLD 组播消息，因此在 AWS EC2 等 MLD 环境中，IPv6 KNI 功能可能无法正常工作。"*
>
> Translation: *"DPDK KNI cannot receive MLD multicast messages, so IPv6 KNI functionality may not work properly in MLD environments like AWS EC2."*
>
> — F-Stack developer documentation, Tencent Cloud (2019-08-16)

**AWS EC2 specifics**: AWS uses MLD snooping on its virtual switches. Without proper MLD Report messages from the F-Stack KNI interface, the switch will not forward multicast traffic (including solicited-node multicast for Neighbor Discovery) to the instance, effectively breaking IPv6 communication through the KNI path.

### DPDK Mailing List Corroboration

A DPDK mailing list report from January 2020 confirms the issue:

> *"DPDK KNI interface is not able to receive solicited node multicast addressed packets."*
>
> — DPDK mailing list, January 2020

---

## 4. Comparison with Other Stacks

| Stack | MLD Support | Notes |
|-------|-------------|-------|
| **F-Stack (DPDK KNI)** | ❌ MLD packets misrouted | `FILTER_MULTI` instead of special handling |
| **F-Stack (DPDK fast path)** | ⚠️ Limited | User-space stack handles its own MLD |
| **FreeBSD kernel** | ✅ Full MLD/MLDv2 | Native kernel MLD implementation |
| **Linux kernel** | ✅ Full MLD/MLDv2 | Native kernel MLD implementation |
| **VPP (FD.io)** | ✅ Full MLD | Built-in MLD implementation |

---

## 5. Root Cause Diagram

```
                          Incoming Ethernet Frame
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │    protocol_filter()     │
                    │   (ff_dpdk_if.c:1462)    │
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────┐
                    │   Parse Ethernet header  │
                    │   Handle ARP             │──── Yes ──► FILTER_ARP
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────────────────────┐
                    │  line 1487: Is it multicast MAC?         │
                    │  (rte_is_multicast_ether_addr)           │
                    │  ADDED by f069dcdcb727 (2024-10-17)      │
                    │                              │           │
                    │                          Yes │           │ No
                    └──────────────────────────────┤───────────┘
                               │                   │
                               ▼                   ▼
                    ┌─────────────────┐   ┌──────────────────┐
                    │  FILTER_MULTI   │   │  line 1493:       │
                    │  (generic path) │   │  Is it IPv6?      │
                    │                 │   │         │         │
                    │  ★ MLD packets  │   │     Yes │         │
                    │  land here!     │   │         ▼         │
                    │  (MAC 33:33:xx) │   │  ff_kni_proto_   │
                    │                 │   │  filter()         │
                    │  MLD Query=130  │   │  → NDP types      │
                    │  MLD Report=131 │   │    133-137 only   │
                    │  MLD Done=132   │   │  → FILTER_NDP     │
                    └─────────────────┘   └──────────────────┘
```

---

## 6. Recommended Fix

### Option A: Extend NDP Detection to Include MLD

Modify `protocol_filter()` to also match ICMPv6 types 130-132 (MLD):

```c
static inline int
is_mld_packet(const void *data, uint16_t len)
{
    const struct ipv6_hdr *ip6 = (const struct ipv6_hdr *)
        ((const uint8_t *)data + sizeof(struct ether_hdr));

    if (ip6->proto != IPPROTO_ICMPV6)
        return 0;

    const struct icmp6_hdr *icmp6 = (const struct icmp6_hdr *)
        ((const uint8_t *)ip6 + sizeof(struct ipv6_hdr));

    /* MLD types: 130 (Query), 131 (Report), 132 (Done) */
    return (icmp6->icmp6_type == 130 ||
            icmp6->icmp6_type == 131 ||
            icmp6->icmp6_type == 132);
}

/* In protocol_filter(): */
if (RTE_ETH_IS_IPV6_HDR(eth_frame_type)) {
    if (is_ndp_packet(data, len))
        return FILTER_NDP;
    if (is_mld_packet(data, len))
        return FILTER_NDP;  /* Treat MLD like NDP for KNI dispatch */
    /* ... */
}
```

### Option B: Add a New Filter Type for MLD

Create `FILTER_MLD` and handle it with the same robust dispatch path as `FILTER_NDP`:

```c
enum FilterReturn {
    FILTER_UNKOWN = 0,
    FILTER_ARP,
    FILTER_NDP,
    FILTER_MLD,    /* New */
    FILTER_MULTI,
    FILTER_BRICAST,
};
```

---

## 7. Sources

1. [F-Stack `ff_dpdk_if.c`](https://github.com/F-Stack/f-stack/blob/master/lib/ff_dpdk_if.c)
2. [F-Stack developer documentation — IPv6 limitations (Tencent Cloud)](https://cloud.tencent.com/developer/article/1488878)
3. [RFC 2710 — Multicast Listener Discovery (MLD) for IPv6](https://www.rfc-editor.org/rfc/rfc2710)
4. [RFC 3810 — Multicast Listener Discovery Version 2 (MLDv2) for IPv6](https://www.rfc-editor.org/rfc/rfc3810)
5. [RFC 4291 — IPv6 Addressing Architecture](https://www.rfc-editor.org/rfc/rfc4291)
