from __future__ import annotations
import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="windsurf-verify", description="Verification runner"
    )
    parser.parse_args(argv)
    print("stub OK: wire to verifier")
    return 0
