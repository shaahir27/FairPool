"""Domain-level failures.

Pure module: no I/O and no framework types, so the same rules back unit,
property and browser-parity tests (T00B01). Error codes that map to HTTP
responses live in ``docs/contracts/config-and-errors.md``; these exceptions are
internal to the domain and never serialise raw text to a client.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for deterministic domain failures."""

    code = "DOMAIN_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ApplicationError(Exception):
    """An allowlisted public error code; no exception details cross the API."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CanonicalJSONError(DomainError, ValueError):
    """Input cannot be encoded with the canonical JSON profile (contract section 1)."""

    code = "CANONICAL_JSON_INVALID"


class HashingError(DomainError, ValueError):
    """A hash, Merkle proof or signature input is malformed."""

    code = "HASHING_INVALID"


class MoneyError(DomainError, ValueError):
    """Money input is not integer cents or a PayPal ``D.CC`` string."""

    code = "MONEY_INVALID"


class AllocationError(DomainError, ValueError):
    """An allocation or waitlist input violates the ranking rules."""

    code = "ALLOCATION_INVALID"


class AuctionError(DomainError, ValueError):
    """A tier, ranking or capacity input violates the auction rules."""

    code = "AUCTION_INVALID"


class UnknownMachine(DomainError):
    """The requested state machine is not defined in ``states.MACHINES``."""

    code = "UNKNOWN_MACHINE"

    def __init__(self, machine: str) -> None:
        super().__init__(f"unknown state machine: {machine}")
        self.machine = machine


class IllegalTransition(DomainError):
    """No transition in the whitelist connects the two states (I10)."""

    code = "ILLEGAL_TRANSITION"

    def __init__(self, machine: str, from_state: str, to_state: str) -> None:
        super().__init__(f"illegal transition for {machine}: {from_state} -> {to_state}")
        self.machine = machine
        self.from_state = from_state
        self.to_state = to_state
