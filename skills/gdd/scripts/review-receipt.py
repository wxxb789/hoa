#!/usr/bin/env python3
"""Validate one fresh pi session receipt against explicit lane identity/transport.

All identity/transport inputs are required flags; no model-name inference or defaults.
Use a new per-round session directory. Stdout is the verified identity JSON, not a report.
"""
import argparse
import json
from pathlib import Path
import sys

from machine_review import EvidenceError, validate_runtime_receipt


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session-dir', type=Path, required=True)
    p.add_argument('--provider', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--transport', choices=('responses', 'other'), required=True)
    p.add_argument('--api-id', action='append', required=True, help='permitted actual API ID; repeat for multiple')
    a = p.parse_args(argv)
    try:
        files = list(a.session_dir.rglob('*.jsonl'))
        if len(files) != 1:
            raise EvidenceError('expected exactly one current-run session receipt')
        records = [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]
        identity = validate_runtime_receipt(records, a.provider, a.model, a.transport, a.api_id)
        identity['session_file'] = str(files[0])
        print(json.dumps(identity, sort_keys=True))
    except (OSError, ValueError, RecursionError) as exc:
        p.error(str(exc))
    return 0


if __name__ == '__main__':
    sys.exit(main())
