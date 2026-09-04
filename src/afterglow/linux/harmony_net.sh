#!/usr/bin/env bash
# harmony_net.sh - bring up the Harmony 900/1000/1100 USB-RNDIS link for concordance on Linux.
#
# THE FIX (found in concordance's start_concordance_dhcpd.sh): the remote does NOT self-assign
# 169.254.1.2. It enumerates as a USB net adapter (Logitech 046d:c11f, a Belcarra MDLM-BLAN device
# driven by the kernel 'zaurus' module) and WAITS FOR A DHCP SERVER to lease it that address.
# Windows' Logitech driver ran one; Linux doesn't. We run dnsmasq as that DHCP server.
#
# CRITICAL detail (kernel log evidence): while waiting the remote TIMES OUT and re-enumerates its
# USB link every ~10-15s, with a NEW MAC each time. So the DHCP server must SURVIVE the interface
# disappearing/reappearing and answer instantly on each cycle. dnsmasq '--bind-interfaces' binds
# once and goes deaf after the first disconnect -> we use '--bind-dynamic' instead, keep dnsmasq
# running across the churn, and re-assert the host IP + NM-unmanaged state every time the
# interface comes back. The remote also changes its *client* MAC at each reboot. Since this helper
# deliberately has a one-address pool, a lease for the old MAC would otherwise prevent the new MAC
# getting 169.254.1.2 for five minutes. The Linux interface MAC does not change, so watching it is
# a trap; instead we watch dnsmasq's definitive `no address available` / socket-bind diagnostics
# and restart only our dnsmasq child, clearing its in-memory lease before the next Discover.
# Eventually a cycle lands inside dnsmasq's window, the remote gets its lease, stops rebooting, and
# concordance can talk to 169.254.1.2:3074.
#
#   sudo ./harmony_net.sh            # auto-detect/wait for the Harmony, then serve DHCP (leave running)
#   sudo ./harmony_net.sh enp4s0f0u14   # or name the interface explicitly
#   (in another terminal, once you see DHCPACK:)  concordance -i   /   concordance -w -C file.ezhex
# Ctrl-C to stop; restores NetworkManager management on exit.
set -uo pipefail

VID=046d; PID=c11f
HOST_IP=169.254.1.1; REMOTE_IP=169.254.1.2; PREFIX=16
[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }
command -v dnsmasq >/dev/null || { echo "dnsmasq not found ('sudo pacman -S dnsmasq')."; exit 1; }
HAVE_NM=$(command -v nmcli >/dev/null && echo 1 || echo 0)

find_iface() {
    local net dev p
    for net in /sys/class/net/*; do
        dev=$(readlink -f "$net/device" 2>/dev/null) || continue
        p="$dev"
        while [[ -n "$p" && "$p" != "/" ]]; do
            if [[ -r "$p/idVendor" && -r "$p/idProduct" \
                  && "$(cat "$p/idVendor")" == "$VID" && "$(cat "$p/idProduct")" == "$PID" ]]; then
                basename "$net"; return 0
            fi
            p=$(dirname "$p")
        done
    done
    return 1
}

# --exit-when-unused LOCKFILE: stop once no Afterglow instance is running.
#
# Afterglow starts this through pkexec, so it runs as root while the application does
# not - and a non-root process cannot signal a root one. Terminating it from the app is
# therefore impossible without asking for a password a second time, at shutdown, which is
# a terrible thing to do to somebody closing a window. So the script watches instead.
#
# It watches a LOCK rather than the pid that started it, because a second window must not
# lose its link when the first one closes. Every instance holds a shared lock on that
# file for as long as it lives; an exclusive lock therefore succeeds only when the last
# one has gone. The kernel drops the lock however the process ends, so a crash is
# indistinguishable from a clean exit and nothing has to be cleaned up.
#
# Only used for the session mode. Started from the udev rule there is nothing to outlive
# and the flag is absent, which is the persistent behaviour that mode is for.
LOCK_FILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --exit-when-unused) LOCK_FILE="${2:-}"; shift 2 ;;
        *) break ;;
    esac
done

nobody_left() {
    # Anything uncertain answers "no" and keeps the link up: leaving a helper running is
    # a smaller harm than cutting the link out from under a remote mid-flash.
    [[ -n "$LOCK_FILE" && -e "$LOCK_FILE" ]] || return 1
    command -v flock >/dev/null 2>&1 || return 1
    flock -n -x "$LOCK_FILE" true 2>/dev/null
}

IFACE="${1:-}"
if [[ -z "$IFACE" ]]; then
    echo "Waiting for the Harmony ($VID:$PID)... (plug it in / it may keep re-appearing)"
    until IFACE=$(find_iface); do
        # Also here: closing the application before ever plugging a remote in would
        # otherwise leave this waiting for good.
        nobody_left && { echo "No Afterglow running; stopping."; exit 0; }
        sleep 0.2
    done
fi
echo "Harmony interface: $IFACE   (it will churn every ~10-15s until it gets its DHCP lease)"

DNSMASQ_PID=""; LOG_READER_PID=""; FW=""
LOG_DIR=""; LOG_FIFO=""; RESTART_REQUEST=""
# Open the firewall for inbound DHCP on this interface. tcpdump sees the Discover but a listening
# daemon does NOT if a firewall drops UDP/67 in INPUT -- exactly the ufw-default-deny case here.
open_fw() {
    if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -qi "Status: active"; then
        ufw allow in on "$IFACE" >/dev/null 2>&1 && FW=ufw && echo "  (ufw: allowed inbound on $IFACE)"
    elif command -v iptables >/dev/null; then
        iptables -I INPUT 1 -i "$IFACE" -p udp --dport 67 -j ACCEPT 2>/dev/null && FW=iptables \
            && echo "  (iptables: accept udp/67 on $IFACE)"
    fi
}
close_fw() {
    [[ "$FW" == ufw ]] && ufw delete allow in on "$IFACE" >/dev/null 2>&1
    [[ "$FW" == iptables ]] && iptables -D INPUT -i "$IFACE" -p udp --dport 67 -j ACCEPT 2>/dev/null
}
cleanup() {
    echo; echo "Cleaning up..."
    stop_dnsmasq
    [[ -n "$LOG_DIR" ]] && rm -rf "$LOG_DIR"
    close_fw
    [[ "$HAVE_NM" == 1 ]] && nmcli device set "$IFACE" managed yes 2>/dev/null
    ip addr del "$HOST_IP/$PREFIX" dev "$IFACE" 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# Give the host its link-local IP BEFORE starting dnsmasq: dnsmasq derives the DHCP subnet from
# the interface address, and answers "no address range" to a DISCOVER if the iface has no address
# in that subnet. We also pin the netmask/router explicitly so it can offer regardless of timing.
setup_iface() {
    [[ "$HAVE_NM" == 1 ]] && nmcli device set "$IFACE" managed no 2>/dev/null
    ip link set "$IFACE" up 2>/dev/null
    ip addr show dev "$IFACE" 2>/dev/null | grep -q "$HOST_IP" || \
        ip addr add "$HOST_IP/$PREFIX" dev "$IFACE" scope link 2>/dev/null
}

# dnsmasq keeps leases in memory even with --leasefile-ro. That is normally what we want: the
# helper leaves no state on the host. Here it means the remote's next random client MAC cannot have
# the only address until the old lease expires. Keeping the child PID means this never kills another
# dnsmasq a user may be running. Its stderr is also the only reliable place to see that client MAC:
# the host-side RNDIS interface has a stable, different MAC.
stop_log_reader() {
    local pid="$LOG_READER_PID"
    LOG_READER_PID=""
    [[ -n "$pid" ]] || return 0
    wait "$pid" 2>/dev/null || true
}

stop_dnsmasq() {
    local pid="$DNSMASQ_PID"
    DNSMASQ_PID=""
    [[ -n "$pid" ]] || return 0
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    stop_log_reader
}

watch_dnsmasq_log() {
    while IFS= read -r line; do
        echo "$line"
        case "$line" in
            *"no address available"*|*"error binding DHCP socket"*)
                # The former is the stale one-address lease. The latter is the same
                # re-enumeration race in an earlier phase: either way, this child is
                # no longer able to serve the remote and must start with fresh state.
                touch "$RESTART_REQUEST"
                ;;
        esac
    done < "$LOG_FIFO"
}

start_log_reader() {
    watch_dnsmasq_log &
    LOG_READER_PID=$!
}

start_dnsmasq() {
    start_log_reader
    dnsmasq -d --port=0 --bind-dynamic --interface="$IFACE" --except-interface=lo \
            --log-dhcp --dhcp-authoritative --leasefile-ro \
            --dhcp-range="$REMOTE_IP,$REMOTE_IP,255.255.0.0,5m" \
            --dhcp-option=option:netmask,255.255.0.0 \
            --dhcp-option=option:router,"$HOST_IP" >"$LOG_FIFO" 2>&1 &
    DNSMASQ_PID=$!
}

restart_dnsmasq() {
    rm -f "$RESTART_REQUEST"
    echo "  DHCP link changed; clearing the old lease and rebinding..."
    stop_dnsmasq
    start_dnsmasq
}

until ip link show "$IFACE" &>/dev/null; do sleep 0.2; done
setup_iface
open_fw
LOG_DIR=$(mktemp -d /tmp/harmony_net.XXXXXX)
LOG_FIFO="$LOG_DIR/dnsmasq.log"
RESTART_REQUEST="$LOG_DIR/restart"
mkfifo "$LOG_FIFO"

# --bind-dynamic survives the interface reappearing; explicit netmask/router satisfy the remote's
# Parameter-Request (Subnet-Mask, Default-Gateway, Broadcast). --log-dhcp shows DISCOVER/OFFER/ACK.
echo "Starting DHCP server (dnsmasq, host $HOST_IP -> leases $REMOTE_IP)..."
start_dnsmasq

# Keep the host IP + NM-unmanaged state in place across any re-enumeration. dnsmasq's diagnostic
# tells us when its single lease belongs to the remote's old random MAC, or its socket lost the
# interface. Restart the child promptly; the following DHCP Discover then sees an empty lease table.
while kill -0 "$DNSMASQ_PID" 2>/dev/null; do
    nobody_left && { echo "No Afterglow running; stopping."; cleanup; }
    if ip link show "$IFACE" &>/dev/null; then
        setup_iface
    fi
    [[ -e "$RESTART_REQUEST" ]] && restart_dnsmasq
    sleep 0.1
done
cleanup
