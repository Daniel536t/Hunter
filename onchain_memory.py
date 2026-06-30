import hashlib, os, datetime
from web3 import Web3
from ipfs_memory import upload_to_ipfs

VAULT_ADDRESS = "0xA9785f5770AA01184a41f422220d0e05175B622d"
RPC_URL = "https://sepolia.base.org"
PRIVATE_KEY = "0xdedc00afc39ff3e5e8e61fdee8a043a3559814088d327284b67f0aeef174a136"

w3 = Web3(Web3.HTTPProvider(RPC_URL))
account = w3.eth.account.from_key(PRIVATE_KEY)

ABI = [
    {"inputs":[{"internalType":"string","name":"_patternId","type":"string"},{"internalType":"string","name":"_name","type":"string"},{"internalType":"string","name":"_description","type":"string"},{"internalType":"string","name":"_codeTemplate","type":"string"},{"internalType":"string[]","name":"_semanticTags","type":"string[]"},{"internalType":"string[]","name":"_features","type":"string[]"}],"name":"storePattern","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"internalType":"string","name":"_patternId","type":"string"}],"name":"getPattern","outputs":[{"internalType":"string","name":"name","type":"string"},{"internalType":"string","name":"description","type":"string"},{"internalType":"string","name":"codeTemplate","type":"string"},{"internalType":"string[]","name":"semanticTags","type":"string[]"},{"internalType":"string[]","name":"features","type":"string[]"},{"internalType":"uint256","name":"successCount","type":"uint256"},{"internalType":"address","name":"creatorAgent","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"string[]","name":"_tags","type":"string[]"},{"internalType":"uint256","name":"_maxResults","type":"uint256"}],"name":"searchByTags","outputs":[{"internalType":"string[]","name":"matchedIds","type":"string[]"},{"internalType":"uint256[]","name":"scores","type":"uint256[]"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"string","name":"_patternId","type":"string"}],"name":"recordSuccess","outputs":[],"stateMutability":"nonpayable","type":"function"},
]

vault = w3.eth.contract(address=VAULT_ADDRESS, abi=ABI)

def _build_pattern_id(challenge, attack_class):
    ts = int(datetime.datetime.now().timestamp() * 1000)
    return f"vuln-{ts}"

def store_pattern_onchain(challenge, attack_class, exploit_body, reasoning):
    content = f"// VulnHunter Memory Pattern\n// Challenge: {challenge}\n// Attack: {attack_class}\n// Reasoning: {reasoning[:200]}\n\n{exploit_body}"
    cid = upload_to_ipfs(content, f"vuln_{challenge}_{attack_class}.sol")
    if not cid: return None
    sha = hashlib.sha256(content.encode()).hexdigest()
    code_template = f"sha256:0x{sha}"
    pattern_id = _build_pattern_id(challenge, attack_class)
    try:
        tx = vault.functions.storePattern(pattern_id, f"Vuln: {challenge}/{attack_class}", reasoning[:200], code_template, ["vulnerability", challenge, attack_class, "exploit"], [f"challenge:{challenge}", f"attack:{attack_class}", f"ipfs:{cid}"]).build_transaction({"from": account.address, "nonce": w3.eth.get_transaction_count(account.address), "gasPrice": w3.eth.gas_price})
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            print(f"  [onchain] Stored {pattern_id} -> tx: {tx_hash.hex()[:16]}... block {receipt.blockNumber}", flush=True)
            return pattern_id
    except Exception as e:
        print(f"  [onchain] Store failed: {e}", flush=True)
    return None

def record_success_onchain(challenge, attack_class, pattern_id=None):
    if not pattern_id: return
    try:
        tx = vault.functions.recordSuccess(pattern_id).build_transaction({"from": account.address, "nonce": w3.eth.get_transaction_count(account.address), "gasPrice": w3.eth.gas_price})
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"  [onchain] Recorded success for {pattern_id}", flush=True)
    except Exception as e:
        print(f"  [onchain] recordSuccess failed: {e}", flush=True)

def search_onchain(challenge, attack_class, max_results=5):
    try:
        ids, scores = vault.functions.searchByTags([challenge, attack_class, "vulnerability"], max_results).call({"from": account.address})
        results = []
        for pid, score in zip(ids, scores):
            try:
                name, desc, code, tags, features, count, creator = vault.functions.getPattern(pid).call({"from": account.address})
                results.append({"pattern_id": pid, "name": name, "description": desc, "code_ref": code, "tags": tags, "success_count": count, "score": score})
            except: pass
        return results
    except Exception as e:
        print(f"  [onchain] Search failed: {e}", flush=True)
        return []

def get_memory_context_onchain(attack_class, challenge):
    patterns = search_onchain(challenge, attack_class)
    if not patterns: return ""
    lines = ["\n### ON-CHAIN MEMORY (Base Sepolia Vault):"]
    for p in patterns:
        lines.append(f"\n// Pattern {p['pattern_id']} (used {p['success_count']}x)")
        lines.append(f"// {p['description'][:150]}")
        lines.append(f"// IPFS ref: {p['code_ref']}")
    return "\n".join(lines)
