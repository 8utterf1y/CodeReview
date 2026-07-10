1. **[ND 10-Option Limit](./01-nd-option-limit.md)**
   [RFC 4861](https://www.rfc-editor.org/rfc/rfc4861) §6.3.4 — Violates **MUST**
   Introduced by [`a9643ea`](https://github.com/F-Stack/f-stack/commit/a9643ea85ce6) (2017-04-21) in `freebsd/netinet6/nd6.c`

2. **[Proxy NA — No Random Delay](./02-proxy-na-no-random-delay.md)**
   [RFC 4861](https://www.rfc-editor.org/rfc/rfc4861) §7.2.8 — Violates **SHOULD**
   Introduced by [`a9643ea`](https://github.com/F-Stack/f-stack/commit/a9643ea85ce6) (2017-04-21) in `freebsd/netinet6/nd6_nbr.c`

3. **[Proxy NA — No Unsolicited NA](./03-proxy-na-no-unsolicited.md)**
   [RFC 4861](https://www.rfc-editor.org/rfc/rfc4861) §7.2.6 — Omitting **MAY**
   Introduced by [`a9643ea`](https://github.com/F-Stack/f-stack/commit/a9643ea85ce6) (2017-04-21) in `freebsd/netinet6/nd6_nbr.c`

4. **[Fragment Chain Not Walked](./04-fragment-header-chain-walking.md)**
   [RFC 8200](https://www.rfc-editor.org/rfc/rfc8200) §4, §4.5 — Violates **MUST**
   Initial DPDK import (all versions) in `dpdk/lib/ip_frag/rte_ip_frag.h`

5. **[No DHCPv6 Support](./05-absent-dhcpv6.md)**
   [RFC 8415](https://www.rfc-editor.org/rfc/rfc8415) — Feature gap
   Never implemented

6. **[MLD Misrouted via KNI](./06-mld-multicast-reception.md)**
   [RFC 2710](https://www.rfc-editor.org/rfc/rfc2710) — Functional failure
   Introduced by [`f069dcd`](https://github.com/F-Stack/f-stack/commit/f069dcdcb727) (2024-10-17) in `lib/ff_dpdk_if.c`
