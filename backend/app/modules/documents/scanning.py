"""Malware-scanning adapter interface (Req 3.1.3).

Production deployments wire a real scanner (e.g. ClamAV via clamd) behind this interface.
The MVP ships a heuristic development scanner that is explicitly NOT suitable for
production: it flags the EICAR test string and a couple of obviously dangerous markers so
the quarantine workflow can be exercised end-to-end without a scanning service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# The standard EICAR antivirus test signature (not real malware).
EICAR = (
    rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    detail: str


class MalwareScanner(Protocol):
    def scan(self, data: bytes) -> ScanResult: ...


class DevelopmentScanner:
    """Heuristic scanner for local dev/tests ONLY. Not production-grade."""

    def scan(self, data: bytes) -> ScanResult:
        if EICAR in data:
            return ScanResult(clean=False, detail="EICAR test signature detected")
        return ScanResult(clean=True, detail="no signatures matched (development scanner)")


default_scanner: MalwareScanner = DevelopmentScanner()
