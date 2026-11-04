#!/bin/sh
# Local/CI mock only: does not connect to or modify a router.
set -eu
script=${1:?Pass path to 98-w1700k-slim-dns-migration}
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/w1700k-dns-test.XXXXXX")
cleanup() {
    case "$test_dir" in "${TMPDIR:-/tmp}"/w1700k-dns-test.*) rm -rf -- "$test_dir";; esac
}
trap cleanup EXIT HUP INT TERM
mkdir "$test_dir/bin"
export DNS_TEST_STATE="$test_dir"
export PATH="$test_dir/bin:$PATH"
cat > "$test_dir/bin/cat" <<'MOCK'
#!/bin/sh
if [ "${1-}" = '/tmp/sysinfo/board_name' ]; then
    [ "${MOCK_BOARD_READ_FAIL-0}" = 0 ] || exit 1
    printf '%s\n' "$MOCK_BOARD"
else
    /bin/cat "$@"
fi
MOCK
cat > "$test_dir/bin/uci" <<'MOCK'
#!/bin/sh
[ "${1-}" != '-q' ] || shift
case "$1" in
get)
    case "$2" in
    'dhcp.@dnsmasq[0].rebind_protection') printf '%s\n' "$MOCK_REBIND";;
    openclash.config.operation_mode) printf '%s\n' "$MOCK_MODE";;
    openclash.config.ipv6_enable) printf '%s\n' "$MOCK_IPV6";;
    openclash.config.ipv6_dns) printf '%s\n' "$MOCK_IPV6_DNS";;
    openclash.config.fakeip_range6)
        if [ -f "$DNS_TEST_STATE/staged" ]; then /bin/cat "$DNS_TEST_STATE/staged"; else /bin/cat "$DNS_TEST_STATE/range"; fi;;
    *) exit 1;;
    esac;;
set)
    printf 'set\n' >> "$DNS_TEST_STATE/calls"
    [ "${MOCK_SET_FAIL-0}" = 0 ] || exit 1
    [ "$2" = 'openclash.config.fakeip_range6=2001:2::1/64' ] || exit 2
    printf '%s\n' '2001:2::1/64' > "$DNS_TEST_STATE/staged";;
commit)
    printf 'commit\n' >> "$DNS_TEST_STATE/calls"
    [ "${MOCK_COMMIT_FAIL-0}" = 0 ] || exit 1
    [ "$2" = openclash ] || exit 2
    mv "$DNS_TEST_STATE/staged" "$DNS_TEST_STATE/range";;
revert)
    printf 'revert\n' >> "$DNS_TEST_STATE/calls"
    [ "$2" = openclash.config.fakeip_range6 ] || exit 2
    rm -f "$DNS_TEST_STATE/staged";;
*) exit 2;;
esac
MOCK
cat > "$test_dir/bin/logger" <<'MOCK'
#!/bin/sh
exit 0
MOCK
chmod +x "$test_dir/bin/"*
reset_case() {
    export MOCK_BOARD='gemtek,w1700k-ubi' MOCK_REBIND=1 MOCK_MODE=fake-ip MOCK_IPV6=1 MOCK_IPV6_DNS=1
    export MOCK_SET_FAIL=0 MOCK_COMMIT_FAIL=0 MOCK_BOARD_READ_FAIL=0
    printf '%s\n' 'fdfe:dcba:9876::1/64' > "$test_dir/range"
    : > "$test_dir/calls"
    rm -f "$test_dir/staged"
}
assert_untouched() {
    sh "$script"
    [ ! -s "$test_dir/calls" ]
}
reset_case
sh "$script"
[ "$(cat "$test_dir/range")" = '2001:2::1/64' ]
[ "$(wc -l < "$test_dir/calls" | tr -d ' ')" = 2 ]
# Repeating an already committed migration must not mutate anything.
: > "$test_dir/calls"
assert_untouched
reset_case; MOCK_BOARD='gemtek,xr1710g-ubi'; assert_untouched
reset_case; MOCK_REBIND=0; assert_untouched
reset_case; MOCK_MODE=redir-host; assert_untouched
reset_case; MOCK_IPV6=0; assert_untouched
reset_case; MOCK_IPV6_DNS=0; assert_untouched
reset_case; printf '%s\n' 'fd12:3456::1/64' > "$test_dir/range"; assert_untouched
reset_case; : > "$test_dir/range"; assert_untouched
reset_case; MOCK_SET_FAIL=1
if sh "$script"; then echo 'set failure unexpectedly succeeded' >&2; exit 1; fi
[ "$(cat "$test_dir/range")" = 'fdfe:dcba:9876::1/64' ]
reset_case; MOCK_COMMIT_FAIL=1
if sh "$script"; then echo 'commit failure unexpectedly succeeded' >&2; exit 1; fi
[ ! -e "$test_dir/staged" ]
[ "$(cat "$test_dir/range")" = 'fdfe:dcba:9876::1/64' ]
MOCK_COMMIT_FAIL=0
sh "$script"
[ "$(cat "$test_dir/range")" = '2001:2::1/64' ]
reset_case; MOCK_BOARD_READ_FAIL=1
if sh "$script"; then echo 'board read failure unexpectedly succeeded' >&2; exit 1; fi
[ ! -s "$test_dir/calls" ]
printf '%s\n' 'PASS: exact migration, idempotence, guards, failure handling, and retry'
