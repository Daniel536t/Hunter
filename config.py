import os

ATTACK_CLASSES = [
    "reentrancy", "access_control", "oracle_manipulation",
    "unchecked_external_call", "delegatecall_injection",
    "flash_loan_logic_abuse", "integer_arithmetic",
    "front_running_mev", "price_calculation_error",
    "signature_replay", "uninitialized_proxy",
]

MAX_HUNT_ITERS   = 4
MAX_PARALLEL     = 2
FORGE_TIMEOUT    = 300
MAX_SOURCE_CHARS = 120_000
