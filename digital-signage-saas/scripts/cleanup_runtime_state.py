#!/usr/bin/env python3
"""Run one cleanup pass for stale runtime data."""

from app import cleanup_runtime_state


if __name__ == "__main__":
    cleanup_runtime_state()
    print("Runtime cleanup completed.")
