from __future__ import annotations

import argparse

from quantum_randomness_service.app import create_app

app = create_app()

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8211)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port)

if __name__ == "__main__":
    main()