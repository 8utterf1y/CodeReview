# Mini F-Stack RFC Consistency Benchmark

This benchmark is a reduced test case for checking code/specification consistency in an IPv6 networking stack.
The repository under audit contains only selected F-Stack source files, but the requirements are written in the
same shape as the full competition task: each requirement names an RFC reference, states the implementation
obligation, and expects evidence from both the specification and the code.

## Requirements

### REQ-ND-OPTIONS

- Requirement: RFC 4861 Section 6.3.4 and Section 4.6.2 say valid Neighbor Discovery options in Router Advertisements MUST be processed without discarding otherwise valid options only because more than a small arbitrary number of options were present.

Keywords: RFC4861, Neighbor Discovery, ND option, Prefix Information option, Router Advertisement, nd6_options.

### REQ-PROXY-NA-RANDOM-DELAY

- Requirement: RFC 4861 Section 7.2.8 says proxy or anycast Neighbor Advertisement behavior SHOULD use a random response delay bounded by MAX_ANYCAST_DELAY_TIME before transmission when responding on behalf of another node.

Keywords: RFC4861, proxy Neighbor Advertisement, MAX_ANYCAST_DELAY_TIME, random delay, nd6_na_output.

### REQ-PROXY-UNSOLICITED-NA

- Requirement: RFC 4861 Section 7.2.6 says a proxy Neighbor Discovery implementation SHOULD support the MAY behavior of sending unsolicited Neighbor Advertisements when proxy state is configured or changes, so that neighbor caches do not remain stale.

Keywords: RFC4861, unsolicited Neighbor Advertisement, proxy, all-nodes multicast, nd6_na_output.

### REQ-IPV6-FRAGMENT-HEADER-CHAIN

- Requirement: RFC 8200 Section 4 and Section 4.5 say IPv6 fragment handling MUST locate a Fragment Header after walking any preceding extension headers, rather than checking only the IPv6 base header immediate Next Header value.

Keywords: RFC8200, IPv6 extension header, Fragment Header, Next Header chain, rte_ipv6_frag_get_ipv6_fragment_header.

### REQ-DHCPV6

- Requirement: RFC 8415 says an IPv6 stack expected to provide DHCPv6 support MUST contain discoverable DHCPv6 client, server, relay, or message-processing entry points.

Keywords: RFC8415, DHCPv6, DHCP6, client, server, relay.

### REQ-MLD-DISPATCH

- Requirement: RFC 2710 says IPv6 MLD packets MUST be delivered to the IPv6 or ICMPv6 stack instead of being diverted to an unrelated host or KNI path before MLD handling can process them.

Keywords: RFC2710, MLD, Multicast Listener Discovery, ICMPv6, ff_dpdk_if, KNI, ff_veth_input.
