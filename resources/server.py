import ipaddress
import json
import logging
import os
import signal
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- Configuration ---
# Configure logging to output to stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

SUBNETS_DATA = [
    {"CIDRBlock":"192.168.0.0/19","AvailabilityZone":"eu-central-1b","AvailabilityZoneId":"euc1-az3"},
    {"CIDRBlock":"192.168.32.0/19","AvailabilityZone":"eu-central-1a","AvailabilityZoneId":"euc1-az2"},
    {"CIDRBlock":"192.168.64.0/19","AvailabilityZone":"eu-central-1c","AvailabilityZoneId":"euc1-az1"},
    {"CIDRBlock":"192.168.96.0/19","AvailabilityZone":"eu-central-1b","AvailabilityZoneId":"euc1-az3"},
    {"CIDRBlock":"192.168.128.0/19","AvailabilityZone":"eu-central-1a","AvailabilityZoneId":"euc1-az2"},
    {"CIDRBlock":"192.168.160.0/19","AvailabilityZone":"eu-central-1c","AvailabilityZoneId":"euc1-az1"}
]

try:
    CIDR_MAPPINGS = {
        ipaddress.ip_network(subnet["CIDRBlock"]): {
            "AvailabilityZone": subnet["AvailabilityZone"],
            "AvailabilityZoneId": subnet["AvailabilityZoneId"]
        } for subnet in SUBNETS_DATA
    }
    logging.info(f"Successfully loaded {len(CIDR_MAPPINGS)} subnet mappings.")
except KeyError as e:
    logging.critical(f"Failed to load or parse subnet information: {e}")
    sys.exit(1)


# --- HTTP Handler ---
class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Handles GET requests."""
        if self.path in ('/healthz', '/readyz'):
            self.send_healthy_response()
            return

        if not self.path.startswith('/'):
            self.send_error_response(400, "Invalid path")
            return
        
        fqdn = self.path.strip('/')
        if not fqdn:
            self.send_error_response(404, "Not Found. Please provide a FQDN in the path, e.g., /my.database.com")
            return

        logging.info(f"Received lookup request for FQDN: {fqdn}")
        try:
            ip_address = self._get_ip_address(fqdn)
            logging.info(f"Resolved {fqdn} to IP address: {ip_address}")

            zone_data = self._get_zone_data(ip_address)
            if zone_data:
                logging.info(f"Found matching zone data for IP {ip_address}")
                self.send_json_response(200, {
                    'zone': zone_data['AvailabilityZone'],
                    'zoneId': zone_data['AvailabilityZoneId']
                })
            else:
                logging.warning(f"No matching zone found for IP {ip_address}")
                self.send_error_response(404, "Zone not found for the given FQDN's IP")

        except socket.gaierror:
            logging.error(f"DNS lookup failed for FQDN: {fqdn}")
            self.send_error_response(404, "FQDN not found or could not be resolved")
        except Exception as e:
            logging.critical(f"An unexpected error occurred for FQDN {fqdn}: {e}", exc_info=True)
            self.send_error_response(500, "Internal Server Error")

    def send_json_response(self, status_code, payload):
        """Sends a JSON response."""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def send_error_response(self, status_code, message):
        """Sends a JSON error response."""
        self.send_json_response(status_code, {'error': message})

    def send_healthy_response(self):
        """Sends a health check response."""
        self.send_json_response(200, {'status': 'ok'})

    def log_message(self, format, *args):
        """Override default logging to use our configured logger, not stderr."""
        logging.info("%s - %s" % (self.address_string(), format % args))

    @staticmethod
    def _get_ip_address(fqdn):
        """Resolves an FQDN to an IP address."""
        return socket.gethostbyname(fqdn)

    @staticmethod
    def _get_zone_data(ip_address_str):
        """Finds the zone data (name and ID) for a given IP address."""
        try:
            ip = ipaddress.ip_address(ip_address_str)
            for network, data in CIDR_MAPPINGS.items():
                if ip in network:
                    return data
        except ValueError:
            logging.warning(f"Invalid IP address format: {ip_address_str}")
        return None


# --- Server and Shutdown Logic ---
def run(server_class=HTTPServer, handler_class=RequestHandler):
    """Starts the HTTP server and sets up graceful shutdown."""
    port = int(os.environ.get("PORT", 8082))
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)

    def shutdown_handler(signum, frame):
        logging.info(f"Received signal {signum}. Shutting down gracefully...")
        # Run shutdown in a separate thread to prevent deadlocking
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logging.info(f"Starting server on http://0.0.0.0:{port}")
    httpd.serve_forever()
    logging.info("Server has shut down.")


if __name__ == "__main__":
    run()
