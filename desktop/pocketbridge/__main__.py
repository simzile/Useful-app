import argparse
import ipaddress
import logging
import threading

from .config import Config
from .server import start_server


def main():
    parser = argparse.ArgumentParser(description="PocketBridge private shared folder")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--state-dir")
    parser.add_argument("--folder")
    parser.add_argument("--host", help="A concrete local IPv4 address, preferably Tailscale")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    config = Config(args.state_dir)
    if args.folder:
        config.data["root"] = args.folder
    if args.host:
        address = ipaddress.ip_address(args.host)
        if address.version != 4 or address.is_unspecified or address.is_multicast:
            parser.error("--host must be a concrete IPv4 address")
        config.data["host"] = str(address)
    if args.port is not None:
        if not 1 <= args.port <= 65535:
            parser.error("--port must be 1..65535")
        config.data["port"] = args.port
    logging.basicConfig(filename=config.directory / "app.log", level=logging.WARNING)
    if args.headless:
        server = start_server(config)
        config.save()
        print(f"PocketBridge running at https://{config.data['host']}:{config.data['port']}")
        print("Credentials are stored in the state directory, not printed to logs.")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            server.shutdown()
            server.server_close()
    else:
        from .gui import DesktopApp
        DesktopApp(config, args.background).run()


if __name__ == "__main__":
    main()

