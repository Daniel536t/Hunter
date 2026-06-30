import json, re
from dataclasses import dataclass

@dataclass
class Invariant:
    name: str
    description: str
    solidity_code: str
    severity: str = "high"
    category: str = "unknown"

def generate_invariants_from_abi(abi: list, source_code: str = "", contract_name: str = "") -> list[Invariant]:
    invariants = []
    has_transfer = any(e.get("type") == "function" and e.get("name") in ("transfer", "transferFrom") for e in abi)
    has_deposit = any(e.get("type") == "function" and e.get("name") in ("deposit", "stake", "mint", "supply") for e in abi)
    has_withdraw = any(e.get("type") == "function" and e.get("name") in ("withdraw", "redeem", "burn", "borrow") for e in abi)
    has_owner = any(e.get("type") == "function" and e.get("name") in ("owner", "admin", "governance") for e in abi)
    has_pause = any(e.get("type") == "function" and e.get("name") in ("pause", "unpause", "halt") for e in abi)
    has_flash_loan = any(e.get("type") == "function" and "flash" in e.get("name","").lower() for e in abi)
    has_balance_of = any(e.get("name") == "balanceOf" for e in abi)
    has_total_supply = any(e.get("name") == "totalSupply" for e in abi)
    is_token = has_balance_of and has_transfer and has_total_supply
    is_vault = has_deposit and has_withdraw
    if has_withdraw: invariants.append(Invariant(name="no-free-withdraw", description="Cannot withdraw more than deposited", solidity_code="assert(balanceBefore >= amount);", severity="critical", category="accounting"))
    if is_token: invariants.append(Invariant(name="total-supply-consistency", description="Sum of all balances equals totalSupply", solidity_code="// Sum of balances == totalSupply", severity="critical", category="accounting"))
    if has_owner: invariants.append(Invariant(name="owner-not-locked", description="Owner/admin functions remain callable by owner", solidity_code="assert(owner != address(0));", severity="high", category="access_control"))
    if has_pause: invariants.append(Invariant(name="pause-consistency", description="When paused, only unpause should work", solidity_code="if(paused){/*only owner can unpause*/}", severity="medium", category="access_control"))
    if has_flash_loan: invariants.append(Invariant(name="flash-loan-repayment", description="Flash loan must be repaid in same transaction", solidity_code="assert(balanceAfter >= balanceBefore - fee);", severity="critical", category="accounting"))
    if is_vault: invariants.append(Invariant(name="deposit-withdraw-symmetry", description="Depositing X then withdrawing should return approximately X", solidity_code="// deposit(X) then withdraw(max) should return ~X", severity="high", category="accounting"))
    invariants.append(Invariant(name="no-arithmetic-overflow", description="Arithmetic operations should not overflow", solidity_code="// Solidity 0.8+ has built-in overflow protection", severity="high", category="arithmetic"))
    return invariants
