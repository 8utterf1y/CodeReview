int nd6_maxndopt = 10;

int nd6_options(void) {
    if (nd6_maxndopt > 0) {
        return nd6_maxndopt;
    }
    return 0;
}
