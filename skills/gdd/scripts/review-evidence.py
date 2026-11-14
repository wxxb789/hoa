#!/usr/bin/env python3
"""Generate a PR comment from a real completed UTF-8 machine-review report.

Usage:
  python review-evidence.py --report REPORT --head FULL_SHA --model MODEL_ID \
      --provider PROVIDER_ID --findings false --output COMMENT

All provenance/findings inputs are explicit flags, with no environment or model
fallbacks. --marker defaults to machine-review-state:v1; --output defaults to
stdout. Does not invoke a reviewer, post a comment, or grant merge permission.
Exit 0: comment generated; 2: usage, evidence, or file error.
"""

import argparse
from pathlib import Path
import sys

from machine_review import DEFAULT_MARKER, EvidenceError, evidence_comment, make_evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="completed UTF-8 report file")
    parser.add_argument("--head", required=True, help="exact full 40-hex reviewed PR head SHA")
    parser.add_argument("--model", required=True, help="operator-selected model identifier (no default)")
    parser.add_argument("--provider", required=True, help="configured provider identifier (no default)")
    parser.add_argument("--findings", choices=("true", "false"), required=True,
                        help="explicit report verdict; true records evidence but blocks merge")
    parser.add_argument("--marker", default=DEFAULT_MARKER, help="marker token (default: %(default)s)")
    parser.add_argument("--output", type=Path, help="comment file (default: UTF-8 stdout)")
    args = parser.parse_args(argv)
    try:
        if args.output is not None and args.output.resolve() == args.report.resolve():
            raise EvidenceError("output must not overwrite the report")
        evidence = make_evidence(args.report.read_bytes(), args.head, args.model,
                                 args.provider, args.findings == "true")
        comment = evidence_comment(evidence, args.marker).encode("utf-8")
        if args.output is None:
            sys.stdout.buffer.write(comment)
        else:
            args.output.write_bytes(comment)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
