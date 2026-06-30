import sqlite3, hashlib

def init():
    c = sqlite3.connect("findings.db")
    c.execute("""CREATE TABLE IF NOT EXISTS findings(
        id TEXT PRIMARY KEY, repo TEXT, attack_class TEXT, target_function TEXT,
        reasoning TEXT, foundry_test TEXT, trace TEXT, validation TEXT,
        reachability TEXT, severity TEXT, root_hash TEXT)""")
    c.commit(); c.close()

def root_hash(exploit_body, *_):
    return hashlib.sha256(exploit_body.encode()).hexdigest()[:16]

def save(repo, task, finding, validation, reachability):
    c = sqlite3.connect("findings.db")
    exploit_body = finding.get("exploit_body", finding.get("foundry_test", ""))
    challenge = finding.get("challenge", task.get("target_contract", "?"))
    attack = finding.get("attack_class", task.get("attack_class", "?"))
    reasoning = finding.get("reasoning", "")
    rh = root_hash(exploit_body)
    fid = hashlib.sha256(f"{repo}{rh}".encode()).hexdigest()[:16]
    exists = c.execute("SELECT 1 FROM findings WHERE root_hash=? AND repo=?", (rh, repo)).fetchone()
    if not exists:
        c.execute("INSERT OR REPLACE INTO findings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (fid, repo, attack, challenge, reasoning, finding.get("foundry_test",""),
             finding.get("execution_trace",""), str(validation),
             str(reachability), reachability.get("estimated_severity","high"), rh))
        c.commit()
    c.close()
    return not exists
