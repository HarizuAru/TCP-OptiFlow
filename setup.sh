#!/bin/bash
# setup.sh - Environment setup script for TCP OptiFlow Emulation Software
# This script should be run on a Linux machine with sudo privileges.

# Exit immediately if a command exits with a non-zero status
set -e

echo "========================================="
echo "   TCP OptiFlow Setup Script (Linux)     "
echo "========================================="

# Check if run as root
if [ "$EUID" -ne 0 ]; then
  echo "[-] Error: Please run this script with sudo (e.g., sudo ./setup.sh)"
  exit 1
fi

echo "[+] Updating package repositories..."
apt-get update -y

echo "[+] Installing system dependencies (Mininet, iperf3, Python3)..."
apt-get install -y mininet iperf3 python3 python3-pip python3-setuptools iproute2

echo "[+] Installing Python libraries..."
# Install Flask, Pandas, and NumPy. We try apt-get first to avoid PEP 668 issues,
# and fallback to pip with --break-system-packages.
apt-get install -y python3-flask python3-pandas python3-numpy || {
  echo "[!] Apt-get python packages failed. Trying pip..."
  pip3 install --upgrade pip
  pip3 install flask pandas numpy --break-system-packages || pip3 install flask pandas numpy
}

echo "[+] Loading TCP BBR kernel module..."
# We use || true in case BBR is already built-in or if it's a VM where modprobe is restricted,
# but we will check availability next.
modprobe tcp_bbr || true

# Check if BBR is successfully loaded
if sysctl net.ipv4.tcp_available_congestion_control | grep -q bbr; then
  echo "[+] TCP BBR is enabled and available."
else
  echo "[!] Warning: TCP BBR is not active in net.ipv4.tcp_available_congestion_control."
  echo "    Ensure your kernel is >= 4.9 and BBR is compiled in or loaded."
fi

# Enable BBR and FQ (BBR requires FQ pacing to work optimally)
echo "[+] Configuring sysctl for BBR and FQ pacing..."
sysctl -w net.core.default_qdisc=fq || true
sysctl -w net.ipv4.tcp_congestion_control=bbr || true

echo "[+] Cleaning up any stale iperf3 processes..."
killall iperf3 2>/dev/null || true

echo "========================================="
echo "[+] Setup complete! You can now run the software:"
echo "    sudo python3 tcp_regime_sim.py"
echo "========================================="
