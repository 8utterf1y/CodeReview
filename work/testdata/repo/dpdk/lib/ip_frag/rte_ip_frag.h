static inline int rte_ipv6_frag_get_ipv6_fragment_header(void *ip6) {
    if (next_header == IPPROTO_FRAGMENT) {
        return 1;
    }
    return 0;
}
