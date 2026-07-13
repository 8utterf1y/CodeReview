void ff_dpdk_if_input(void) {
    if (ether_type == ETHER_TYPE_IPV6) {
        handle_ipv6();
    }
}
