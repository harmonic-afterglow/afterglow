#!/usr/bin/env bash
# Install the permanent Harmony auto-DHCP integration (udev rule + takeover script),
# or with `direct`, the rule that gives Afterglow direct access instead.
# After this, just plug in the remote and run `concordance -i` / the GUI Flash button -- the
# network comes up automatically. Undo: sudo ./install_harmony_udev.sh uninstall
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }

if [[ "${1:-}" == "uninstall" ]]; then
    rm -f /usr/local/bin/harmony_net.sh /etc/udev/rules.d/99-harmony-usbnet.rules \
          /etc/udev/rules.d/70-afterglow-harmony.rules
    udevadm control --reload-rules && udevadm trigger
    echo "Uninstalled."; exit 0
fi

# Direct access replaces the network link: the remote is opened over USB, so the DHCP
# helper is removed rather than left to set up an interface nothing uses.
if [[ "${1:-}" == "direct" ]]; then
    install -Dm644 "$HERE/70-afterglow-harmony.rules" /etc/udev/rules.d/70-afterglow-harmony.rules
    rm -f /usr/local/bin/harmony_net.sh /etc/udev/rules.d/99-harmony-usbnet.rules
    udevadm control --reload-rules && udevadm trigger
    echo "Direct access installed. Unplug the remote and plug it back in."; exit 0
fi

command -v dnsmasq  >/dev/null || echo "WARNING: dnsmasq not installed -> 'sudo pacman -S dnsmasq'"
command -v systemd-run >/dev/null || echo "WARNING: systemd-run missing (systemd required)"

install -Dm755 "$HERE/harmony_net.sh"            /usr/local/bin/harmony_net.sh
install -Dm644 "$HERE/99-harmony-usbnet.rules"   /etc/udev/rules.d/99-harmony-usbnet.rules
udevadm control --reload-rules && udevadm trigger
echo "Installed. Plug in the Harmony; check with:  ip addr   (host should get 169.254.1.1)"
echo "Watch the DHCP lease:  journalctl -fu 'harmony-net-*'"
