#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# WireGuard VPN Setup — connects VPS to local machine
#
# Creates a point-to-point WireGuard tunnel so the VPS NATS leaf node
# can bridge to the home NATS cluster and the local machine can reach
# the VPS PostgreSQL and services.
#
# Usage:
#   On VPS:   scripts/setup_wireguard.sh server
#   On local: scripts/setup_wireguard.sh client <VPS_PUBLIC_IP>
#
# Prerequisites:
#   - wireguard-tools installed (apt install wireguard-tools)
#   - Root or sudo access
#   - UDP port 51820 open in VPS firewall
#
# Network layout:
#   Local  (client) → 10.0.100.2/24
#   VPS    (server) → 10.0.100.1/24
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

WG_INTERFACE="wg-trading"
WG_PORT=51820
WG_DIR="/etc/wireguard"
SERVER_IP="10.0.100.1/24"
CLIENT_IP="10.0.100.2/24"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo -e "${YELLOW}[info]${NC}  $1"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $1"; }
error() { echo -e "${RED}[error]${NC} $1"; exit 1; }

check_root() {
  if [ "$EUID" -ne 0 ]; then
    error "This script must be run as root (use sudo)"
  fi
}

ensure_wireguard() {
  if ! command -v wg &> /dev/null; then
    error "wireguard-tools not installed. Run: apt install wireguard-tools (or brew install wireguard-tools on macOS)"
  fi
}

generate_keys() {
  local name="$1"
  local key_file="${WG_DIR}/${name}_privatekey"
  local pub_file="${WG_DIR}/${name}_publickey"

  if [ -f "$key_file" ]; then
    info "Keys already exist for $name — reusing"
  else
    mkdir -p "$WG_DIR"
    wg genkey | tee "$key_file" | wg pubkey > "$pub_file"
    chmod 600 "$key_file"
    ok "Generated keys for $name"
  fi
}

# ── Server setup (run on VPS) ─────────────────────────────────────────

setup_server() {
  check_root
  ensure_wireguard
  generate_keys "server"

  local priv_key
  priv_key=$(cat "${WG_DIR}/server_privatekey")

  cat > "${WG_DIR}/${WG_INTERFACE}.conf" <<EOF
[Interface]
PrivateKey = ${priv_key}
Address = ${SERVER_IP}
ListenPort = ${WG_PORT}
SaveConfig = false

# Client peer — paste the client public key here after running
# setup_wireguard.sh client on the local machine.
# [Peer]
# PublicKey = <CLIENT_PUBLIC_KEY>
# AllowedIPs = 10.0.100.2/32
EOF

  chmod 600 "${WG_DIR}/${WG_INTERFACE}.conf"

  # Enable and start
  systemctl enable "wg-quick@${WG_INTERFACE}" 2>/dev/null || true
  wg-quick up "$WG_INTERFACE" 2>/dev/null || wg-quick down "$WG_INTERFACE" && wg-quick up "$WG_INTERFACE"

  echo ""
  ok "WireGuard server configured on ${SERVER_IP}"
  echo ""
  echo "Server public key (give this to the client):"
  echo -e "  ${GREEN}$(cat "${WG_DIR}/server_publickey")${NC}"
  echo ""
  echo "Next steps:"
  echo "  1. Run on local machine: sudo scripts/setup_wireguard.sh client <VPS_PUBLIC_IP>"
  echo "  2. Copy the client public key output"
  echo "  3. Add [Peer] block to ${WG_DIR}/${WG_INTERFACE}.conf on this VPS"
  echo "  4. Run: wg-quick down $WG_INTERFACE && wg-quick up $WG_INTERFACE"
}

# ── Client setup (run on local machine) ───────────────────────────────

setup_client() {
  local vps_ip="${1:-}"
  if [ -z "$vps_ip" ]; then
    error "Usage: setup_wireguard.sh client <VPS_PUBLIC_IP>"
  fi

  check_root
  ensure_wireguard
  generate_keys "client"

  local priv_key
  priv_key=$(cat "${WG_DIR}/client_privatekey")

  echo ""
  read -rp "Paste the VPS server public key: " server_pubkey
  echo ""

  cat > "${WG_DIR}/${WG_INTERFACE}.conf" <<EOF
[Interface]
PrivateKey = ${priv_key}
Address = ${CLIENT_IP}

[Peer]
PublicKey = ${server_pubkey}
Endpoint = ${vps_ip}:${WG_PORT}
AllowedIPs = 10.0.100.0/24
PersistentKeepalive = 25
EOF

  chmod 600 "${WG_DIR}/${WG_INTERFACE}.conf"

  wg-quick up "$WG_INTERFACE" 2>/dev/null || (wg-quick down "$WG_INTERFACE" 2>/dev/null; wg-quick up "$WG_INTERFACE")

  echo ""
  ok "WireGuard client configured on ${CLIENT_IP}"
  echo ""
  echo "Client public key (add this to the VPS server config):"
  echo -e "  ${GREEN}$(cat "${WG_DIR}/client_publickey")${NC}"
  echo ""
  echo "Testing connectivity..."
  if ping -c 2 -W 3 10.0.100.1 > /dev/null 2>&1; then
    ok "VPS reachable at 10.0.100.1"
  else
    echo -e "  ${YELLOW}⚠ Cannot reach VPS yet. Make sure the [Peer] block is added on the server.${NC}"
  fi
}

# ── NATS leaf node config ─────────────────────────────────────────────

generate_nats_leaf_config() {
  info "Generating NATS leaf node configuration..."

  cat > "configs/nats-leaf.conf" <<'EOF'
# NATS Leaf Node configuration for VPS
# Place this in the VPS NATS container or mount as a volume.

port: 4222
http_port: 8222

leafnodes {
  port: 7422
  remotes [
    {
      # Local NATS cluster via WireGuard
      url: "nats://10.0.100.2:7422"
    }
  ]
}

# Subjects routed between VPS and local
# All trading-related subjects are forwarded automatically
EOF

  ok "NATS leaf config written to configs/nats-leaf.conf"
  echo "  Mount this in the VPS NATS container:"
  echo "    volumes:"
  echo "      - ./configs/nats-leaf.conf:/etc/nats/nats.conf:ro"
  echo "    command: ['--config', '/etc/nats/nats.conf']"
}

# ── Main ──────────────────────────────────────────────────────────────

case "${1:-}" in
  server)
    setup_server
    generate_nats_leaf_config
    ;;
  client)
    setup_client "${2:-}"
    ;;
  nats-config)
    generate_nats_leaf_config
    ;;
  *)
    echo "Usage: $0 {server|client <VPS_IP>|nats-config}"
    echo ""
    echo "  server      — Run on VPS to set up WireGuard server"
    echo "  client IP   — Run on local machine to connect to VPS"
    echo "  nats-config — Generate NATS leaf node config only"
    exit 1
    ;;
esac
