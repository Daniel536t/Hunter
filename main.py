import asyncio, sys, subprocess, tempfile, pathlib, shutil
sys.stdout.reconfigure(line_buffering=True)
from orchestrator import run

def clone_repo(url: str) -> pathlib.Path:
    print("Cloning...", flush=True)
    d = pathlib.Path(tempfile.mkdtemp()) / "target"
    d.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", url, str(d)], check=True, capture_output=True)
    print("Building...", flush=True)
    subprocess.run(["forge", "build", "--build-info"], cwd=d, capture_output=True)
    print("Build done.", flush=True)
    return d

if __name__ == "__main__":
    target = sys.argv[1]
    if target.startswith("http://") or target.startswith("https://") or target.endswith(".git"):
        repo = clone_repo(target)
    elif target.startswith("0x"):
        from etherscan_extractor import get_contract
        network = sys.argv[2] if len(sys.argv) > 2 else "ethereum"
        info = get_contract(target, network)
        if not info: sys.exit(1)
        d = pathlib.Path(tempfile.mkdtemp()) / "target"; d.mkdir(parents=True)
        subprocess.run(["forge", "init", "--force", "--no-commit"], cwd=d, capture_output=True)
        subprocess.run(["forge", "install", "foundry-rs/forge-std"], cwd=d, capture_output=True)
        (d/"src"/f"{info.name}.sol").write_text(info.source_code)
        subprocess.run(["forge", "build", "--build-info"], cwd=d, capture_output=True)
        repo = d
    else:
        repo = pathlib.Path(target)
        if not repo.exists(): print(f"Path not found: {target}"); sys.exit(1)
    try:
        results = asyncio.run(run(repo))
        print(f"\n=== {len(results)} confirmed findings ===", flush=True)
        for item in results:
            if isinstance(item, Exception): print(f"  ERROR: {item}", flush=True); continue
            task, finding, validation, reachability = item
            print(f"\n  CONFIRMED: {finding.get('challenge','?')} / {task.get('attack_class','?')}", flush=True)
            print(f"  Reasoning: {finding.get('reasoning','')[:200]}", flush=True)
    finally: shutil.rmtree(repo, ignore_errors=True)
