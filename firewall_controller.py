from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.addresses import IPAddr, EthAddr

log = core.getLogger()

# Database to store MAC to Port mappings (Host Discovery)
host_db = {}  # allows controller to act as learning switch

# Constraint: Blocked Pair (Example: h1 to h3)
BLOCKED_SRC_IP = "10.0.0.1"
BLOCKED_DST_IP = "10.0.0.3"

def show_hosts():
    """Display all discovered hosts with their MAC address and port."""
    if not host_db:
        log.info("No hosts discovered yet.")
        return
    log.info("------ Host Details ------")
    for mac, port in host_db.items():
        log.info("Host MAC: %s  ->  Port: %s", mac, port)
    log.info("--------------------------")

def _handle_ConnectionUp(event):
    log.info("Switch %s has connected!", event.dpid)

def _handle_PacketIn(event):
    # Triggered when switch does not know how to forward a packet
    packet = event.parsed
    if not packet:
        return

    # 1. Define variables
    src_mac = packet.src
    dst_mac = packet.dst
    in_port = event.port

    # 2. Host Discovery: Learn/Update MAC -> Port mapping
    if src_mac not in host_db:
        host_db[src_mac] = in_port
        log.info("New Host Discovered: %s on port %s", src_mac, in_port)
        show_hosts()  # Display all hosts whenever a new host joins
    else:
        host_db[src_mac] = in_port  # Update port if host moved

    # 3. Handle IPv4 Logic (Firewall)
    ip_packet = packet.find('ipv4')
    if ip_packet:
        src_ip = str(ip_packet.srcip)
        dst_ip = str(ip_packet.dstip)

        if src_ip == BLOCKED_SRC_IP and dst_ip == BLOCKED_DST_IP:
            log.info("FIREWALL: Blocking traffic %s -> %s", src_ip, dst_ip)
            
            # Install an explicit DROP flow rule (High Priority)
            msg = of.ofp_flow_mod()
            msg.priority = 65535
            msg.match.dl_type = 0x0800  # IPv4
            msg.match.nw_src = ip_packet.srcip
            msg.match.nw_dst = ip_packet.dstip
            # No actions = DROP
            event.connection.send(msg)
            return

    # 4. Learning Switch Logic
    if dst_mac in host_db:
        out_port = host_db[dst_mac]
        log.info("Match-Action: %s -> %s [Output Port %s]", src_mac, dst_mac, out_port)

        # Install Flow Rule
        msg = of.ofp_flow_mod()
        msg.match = of.ofp_match.from_packet(packet, in_port)
        msg.priority = 10
        msg.actions.append(of.ofp_action_output(port=out_port))
        event.connection.send(msg)

        # Forward current packet
        packet_out = of.ofp_packet_out()
        packet_out.data = event.ofp
        packet_out.actions.append(of.ofp_action_output(port=out_port))
        event.connection.send(packet_out)
    else:
        # Unknown destination: Flood
        log.debug("Unknown dest %s, flooding...", dst_mac)
        msg = of.ofp_packet_out()
        msg.data = event.ofp
        msg.actions.append(of.ofp_action_output(port=of.OFPP_FLOOD))
        event.connection.send(msg)

def launch():
    core.openflow.addListenerByName("ConnectionUp", _handle_ConnectionUp)
    core.openflow.addListenerByName("PacketIn", _handle_PacketIn)
    log.info("Firewall Controller Logic Started.")

