import asyncio, pathlib
import config, db
from recon import recon
from solve import solve_challenge, find_challenge_test
from llm import llm, HUNTER_MODEL
from scaffold_autofix import generate_scaffold_autofix
from generic_scaffold import assemble_test, extract_contracts
from invariant_generator import generate_invariants_from_abi

async def _process(task, repo, source, sem):
    async with sem:
        contract = task.get("target_contract", "?"); atk = task.get("attack_class", "?")
        challenge_map = {"TrusterLenderPool":"truster","SelfiePool":"selfie","UnstoppableVault":"unstoppable","NaiveReceiverPool":"naive-receiver","SideEntranceLenderPool":"side-entrance","PuppetPool":"puppet","PuppetV2Pool":"puppet-v2","PuppetV3Pool":"puppet-v3","ClimberVault":"climber","FreeRiderNFTMarketplace":"free-rider","ShardsNFTMarketplace":"shards","TheRewarderDistributor":"the-rewarder"}
        challenge = None
        for cname, cdir in challenge_map.items():
            if cname.lower() in contract.lower(): challenge = cdir; break
        if not challenge: challenge = contract.lower().replace("pool","").replace("vault","")
        print(f"[hunt] {atk} -> {contract} (challenge: {challenge})", flush=True)
        dvd_test = find_challenge_test(repo, challenge)
        if dvd_test:
            print(f"  [scaffold] Using DVD test", flush=True)
            from scaffold import use_existing_dvd_test, extract_dvd_symbols
            dvd = use_existing_dvd_test(repo, contract)
            available = extract_dvd_symbols(dvd["full_source"]) if dvd else ""
            task["available_symbols"] = available
            finding = await solve_challenge(challenge=challenge, repo=repo, task=task, source_slice=source[:5000], llm_fn=llm, hunter_model=HUNTER_MODEL, max_iters=4)
        else:
            print(f"  [scaffold] Generating generic scaffold...", flush=True)
            scaf = generate_scaffold_autofix(repo, contract)
            if not scaf or not scaf.compiles: print(f"  [scaffold] Failed for {contract}"); return None
            contracts = extract_contracts(repo)
            if contract in contracts:
                ci = contracts[contract]
                invariants = generate_invariants_from_abi(ci.abi, '', contract)
                print(f"  [invariants] {len(invariants)} generated", flush=True)
                task["invariants"] = [{"name":i.name,"description":i.description} for i in invariants]
            task["available_symbols"] = scaf.abi_summary
            test_code = assemble_test(scaf, "// exploit here", "assertTrue(false, 'not yet exploited');")
            test_path = repo / "test" / f"Hunt_{contract}.t.sol"
            test_path.parent.mkdir(exist_ok=True, parents=True)
            test_path.write_text(test_code)
            print(f"  [hunt] Generic scaffold ready for {contract}", flush=True)
            return None
        if finding:
            validation = finding["validation"]; reachability = {"reachable":True,"estimated_severity":"high"}
            is_new = db.save(str(repo), task, finding, validation, reachability)
            tag = "NEW" if is_new else "dup"
            print(f"  CONFIRMED: {finding.get('challenge',contract)} / {atk} ({tag})", flush=True)
            return (task, finding, validation, reachability)
        return None

async def run(repo: pathlib.Path, target_contract: str = None):
    db.init()
    source, tasks = await recon(repo)
    if target_contract: tasks = [t for t in tasks if t.get("target_contract") == target_contract]
    print(f"[recon] {len(tasks)} tasks", flush=True)
    sem = asyncio.Semaphore(config.MAX_PARALLEL)
    results = await asyncio.gather(*[_process(t, repo, source, sem) for t in tasks], return_exceptions=True)
    return [r for r in results if r and not isinstance(r, Exception)]
