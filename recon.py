import json, subprocess, pathlib
import config, prompts
from llm import llm, parse_json, RECON_MODEL

def run_slither(repo: pathlib.Path) -> str:
    try:
        out = subprocess.run(["slither", str(repo), "--json", "-"], capture_output=True, text=True, timeout=300)
        return (out.stdout or out.stderr)[:8000]
    except Exception as e:
        return f"slither failed: {e}"

def read_source(repo: pathlib.Path) -> str:
    source_files = []
    for f in sorted(repo.rglob("*.sol")):
        if f.is_dir(): continue
        s = str(f).lower()
        if any(x in s for x in ["test/", "mock/", "node_modules", "lib/forge-std", "/out/"]): continue
        source_files.append(f)
    blob, total = [], 0
    for f in source_files:
        txt = f.read_text(errors="ignore")
        blob.append(f"// FILE: {f.relative_to(repo)}\n{txt}")
        total += len(txt)
        if total > config.MAX_SOURCE_CHARS: break
    foundry_toml = repo / "foundry.toml"
    if foundry_toml.exists():
        remap = f"\n// FOUNDRY CONFIG:\n{foundry_toml.read_text()[:2000]}"
        blob.insert(0, remap)
    return "\n\n".join(blob)

async def recon(repo: pathlib.Path):
    source = read_source(repo)
    slither = run_slither(repo)
    user = prompts.RECON_USER.format(attack_classes=config.ATTACK_CLASSES, slither=slither, source=source)
    print(f"[recon] Calling LLM (prompt: {len(user)} chars)...", flush=True)
    raw = await llm(RECON_MODEL, prompts.RECON_SYS, user, temp=0.4, max_tokens=16384)
    print(f"[recon] LLM returned {len(raw) if raw else 0} chars", flush=True)
    tasks = parse_json(raw)
    print(f"[recon] parse_json -> {type(tasks).__name__}, len={len(tasks) if tasks else 'None'}", flush=True)
    if not tasks:
        if raw: print(f"[recon] RAW first 300: {raw[:300]}", flush=True)
        return source, []
    from generic_scaffold import extract_contracts
    real_contracts = set(extract_contracts(repo).keys())
    print(f"[recon] Build has {len(real_contracts)} contracts", flush=True)
    task_contracts = set(t.get("target_contract", "") for t in tasks)
    missing = task_contracts - real_contracts
    if missing: print(f"[recon] {len(missing)} contracts in tasks NOT in build: {list(missing)[:5]}", flush=True)
    before = len(tasks)
    tasks = [t for t in tasks if t.get("target_contract", "") in real_contracts]
    print(f"[recon] filtered {before-len(tasks)} hallucinated tasks, {len(tasks)} remain", flush=True)
    tasks.sort(key=lambda t: t.get("priority", 0), reverse=True)
    return source, tasks
