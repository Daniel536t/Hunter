import json, hashlib, pathlib
from datetime import datetime

MEMORY_FILE = pathlib.Path.home() / "hunter" / "hunt_memory.jsonl"

def store_finding(challenge, attack_class, exploit_body, reasoning):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "challenge": challenge,
        "attack_class": attack_class,
        "exploit_body": exploit_body,
        "reasoning": reasoning,
        "sha256": hashlib.sha256(exploit_body.encode()).hexdigest()[:16],
    }
    existing = query_by_hash(entry["sha256"])
    if existing: return None
    with open(MEMORY_FILE, "a") as f: f.write(json.dumps(entry) + "\n")
    return entry["sha256"]

def query_by_hash(sha256_prefix):
    if not MEMORY_FILE.exists(): return []
    results = []
    with open(MEMORY_FILE) as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry["sha256"].startswith(sha256_prefix): results.append(entry)
            except: pass
    return results

def query_by_challenge(challenge):
    if not MEMORY_FILE.exists(): return []
    results = []
    with open(MEMORY_FILE) as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry["challenge"] == challenge: results.append(entry)
            except: pass
    return results

def query_by_attack_class(attack_class):
    if not MEMORY_FILE.exists(): return []
    results = []
    with open(MEMORY_FILE) as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry["attack_class"] == attack_class: results.append(entry)
            except: pass
    return results

def get_memory_context(attack_class, challenge):
    patterns = query_by_attack_class(attack_class) + query_by_challenge(challenge)
    if not patterns: return ""
    lines = ["\n### PAST CONFIRMED EXPLOITS FROM MEMORY:"]
    seen = set()
    for p in patterns[-5:]:
        if p["sha256"] not in seen:
            seen.add(p["sha256"])
            lines.append(f"\n// Memory {p['sha256']} — {p['challenge']}/{p['attack_class']}")
            lines.append(f"// {p['reasoning'][:200]}")
            lines.append(p["exploit_body"][:500])
    return "\n".join(lines)
