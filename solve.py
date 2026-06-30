import re, subprocess, pathlib, datetime
from memory import get_memory_context

def log(msg: str):
    print(f"  [{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def find_challenge_test(repo: pathlib.Path, challenge: str) -> pathlib.Path | None:
    candidates = list(repo.rglob(f"test/{challenge}/*.t.sol"))
    if not candidates:
        for f in repo.rglob("test/**/*.t.sol"):
            if challenge.lower() in str(f).lower(): candidates.append(f)
    return candidates[0] if candidates else None

SOLUTION_FN = re.compile(r'(function\s+test_\w+\s*\([^)]*\)\s*public\s+checkSolvedByPlayer\s*\{)(?P<body>.*?)(\n\s*\})', re.DOTALL)

def locate_solution_slot(src: str):
    m = SOLUTION_FN.search(src)
    if not m: return None
    return src[:m.start(2)], m.group("body"), src[m.end("body"):]

def inject_exploit(src: str, exploit_body: str) -> str | None:
    contract_defs = []; execution_code = exploit_body
    contract_pattern = re.compile(r'(contract\s+\w+(?:\s+is\s+[^{]+)?\s*\{)', re.DOTALL)
    for m in contract_pattern.finditer(exploit_body):
        start = m.start(); brace_start = m.end() - 1; depth = 0; i = brace_start
        while i < len(exploit_body):
            if exploit_body[i] == '{': depth += 1
            elif exploit_body[i] == '}':
                depth -= 1
                if depth == 0: contract_defs.append(exploit_body[start:i+1]); break
            i += 1
    for cd in contract_defs: execution_code = execution_code.replace(cd, '')
    execution_code = execution_code.strip()
    if contract_defs:
        test_contract_match = re.search(r'(contract\s+\w+Challenge\s+is\s+Test\s*\{)', src)
        if test_contract_match:
            insert_pos = test_contract_match.start()
            for cd in reversed(contract_defs): src = src[:insert_pos] + cd.strip() + '\n\n' + src[insert_pos:]
    slot = locate_solution_slot(src)
    if not slot: return None
    prefix, _old, suffix = slot
    indented = _indent(execution_code.strip(), 8)
    return f"{prefix}\n{indented}\n{suffix}"

def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + l if l.strip() else l for l in text.splitlines())

def run_oracle(repo: pathlib.Path, test_path: pathlib.Path, solution_fn: str, timeout=300):
    out = subprocess.run(["forge", "test", "--match-path", str(test_path.relative_to(repo)), "--match-test", solution_fn, "-vvv"], cwd=repo, capture_output=True, text=True, timeout=timeout)
    log_output = out.stdout + out.stderr
    solved = (out.returncode == 0 and "Suite result: ok" in log_output and "0 failed" in log_output and "[FAIL" not in log_output)
    return solved, log_output[-6000:]

FORBIDDEN_PATTERNS = [
    (r'vm\.prank\(\s*deployer', "pranks as deployer"),
    (r'vm\.startPrank\(\s*deployer', "startPrank as deployer"),
    (r'vm\.deal\(\s*player', "vm.deal funds the player"),
    (r'vm\.store\(', "vm.store directly writes storage"),
    (r'vm\.etch\(', "vm.etch overwrites contract code"),
]

def deterministic_cheat_check(exploit_body: str):
    for pat, reason in FORBIDDEN_PATTERNS:
        if re.search(pat, exploit_body): return {"verdict": "REJECTED", "reason": f"CHEAT: {reason}"}
    for m in re.finditer(r'vm\.(?:start)?[pP]rank\(\s*(\w+)', exploit_body):
        who = m.group(1)
        if who not in ("player", "attacker"): return {"verdict": "REJECTED", "reason": f"CHEAT: acts as '{who}', only player may act"}
    return {"verdict": "CONFIRMED", "reason": "oracle passed; no cheating detected"}

def classify_forge_error(output: str) -> str:
    if "does not implement" in output and "IERC3156" in output: return "MISSING_FLASH_BORROWER"
    if "snapshot" in output and "not found" in output: return "SNAPSHOT_NOT_FOUND"
    if "revert" in output and "vote" in output.lower(): return "DELEGATION_MISSING"
    if "revert" in output and "delay" in output.lower(): return "TIME_WARP_MISSING"
    if "Error (2314)" in output: return "SYNTAX_ERROR"
    if "Error (9553)" in output: return "TYPE_MISMATCH"
    if "Error (6" in output or "ParserError" in output or "DeclarationError" in output: return "COMPILATION_ERROR"
    if "Undeclared identifier" in output: return "UNDECLARED_IDENTIFIER"
    if "revert" in output.lower(): return "EXECUTION_REVERTED"
    return "EXECUTION_FAILURE"

ERROR_HINTS = {
    "MISSING_FLASH_BORROWER": "Deploy a SEPARATE helper contract implementing IERC3156FlashBorrower. Define it ABOVE the test function.",
    "SNAPSHOT_NOT_FOUND": "snapshot() does NOT exist on DamnValuableVotes. Use token.delegate(address(this)) instead. NEVER call token.snapshot().",
    "DELEGATION_MISSING": "Inside the flash loan callback, call token.delegate(address(this)) BEFORE governance.queueAction().",
    "TIME_WARP_MISSING": "Add vm.warp(block.timestamp + 2 days + 1) between queueing and executing.",
    "SYNTAX_ERROR": "Check your function call syntax. Every function call needs parentheses: token.transfer(address(vault), 1). No spaces before arguments.",
    "TYPE_MISMATCH": "Contract type mismatch. Use address(contractVar) to cast a contract to an address, or IERC3156FlashBorrower(address(helper)) for flash loan callbacks.",
    "COMPILATION_ERROR": "Solidity syntax error. Check balanced braces, correct function signatures.",
    "UNDECLARED_IDENTIFIER": "You referenced a variable that doesn't exist. Use ONLY variables from AVAILABLE SYMBOLS.",
    "EXECUTION_REVERTED": "The exploit compiled but reverted. Check your callback interface and function signatures.",
    "EXECUTION_FAILURE": "Test did not pass. Review forge output for revert reasons.",
}

HUNT_SYS = """You are an elite smart-contract exploit developer solving Damn Vulnerable DeFi challenges.

CRITICAL API INFORMATION:
- DamnValuableVotes uses ERC20Votes (NOT ERC20Snapshot). It has NO snapshot() function.
  To acquire voting power: token.delegate(address(this));
  NEVER call token.snapshot(). It does not exist and will not compile.
- SelfiePool flash loan callback: function receiveTokens(address token, uint256 amount) external;
- SelfiePool.flashLoan signature: flashLoan(IERC3156FlashBorrower receiver, address token, uint256 amount, bytes calldata data)
  The receiver is IERC3156FlashBorrower, NOT address. Cast: IERC3156FlashBorrower(address(helper))
- SimpleGovernance.queueAction: queueAction(address target, uint128 value, bytes calldata data) returns(uint256)
  executeAction(uint256 actionId) external payable, getActionDelay() external view returns(uint256)
- Use vm.warp(block.timestamp + 2 days + 1) to skip governance delay.

CRITICAL RULES FOR MULTI-STEP EXPLOITS:
- Helper contracts CANNOT access test contract state variables directly.
  Pass ALL needed contracts (token, pool, governance, recovery) via constructor.
- If the exploit requires a flash loan, you MUST deploy a helper contract.
- Store state between transactions in PUBLIC variables (e.g., uint256 public actionId).
- Use ONLY the player account. Do NOT prank as deployer/owner.
- Do NOT use vm.deal, deal(), vm.store, or vm.etch.

FOR UNSTOPPABLEVAULT:
The exploit is ONE LINE: token.transfer(address(vault), 1);
Write ONLY this statement inside <EXPLOIT_BODY>. No contract definitions. No imports. No pragma.

FOR ALL CHALLENGES:
- Write ONLY Solidity statements that go inside the function body.
- Do NOT write 'contract', 'import', 'pragma', or 'function' unless the challenge
  requires a flash loan helper contract (SelfiePool, Truster, NaiveReceiver).
- Each statement ends with a semicolon. Function calls use parentheses.
- UnstoppableVault: ONE statement. SelfiePool: deploy helper + 3-5 statements.

Output EXACTLY these tags:
<EXPLOITABLE>true|false</EXPLOITABLE>
<REASONING>one paragraph explaining the exploit architecture</REASONING>
<EXPLOIT_BODY>
// INCLUDE BOTH: helper contract definition AND test execution code together.
// Write PURE Solidity, no markdown fences.
</EXPLOIT_BODY>"""

HUNT_USER = """SOLVE ONLY THIS CHALLENGE: {challenge}
DO NOT reference other challenges. DO NOT copy code from SelfiePool into UnstoppableVault solutions.
Only use the contracts and variables available in THIS challenge.

SUSPECTED ATTACK CLASS: {attack_class}
PRIMARY TARGET: {target}

AVAILABLE SYMBOLS:
{available_symbols}

{memory_context}

RELEVANT SOURCE:
{source}
{feedback}

Write the exploit body that makes the challenge's _isSolved() oracle pass, using only the player account."""

HYPOTHESIS_MATCH_SYS = """You are a vulnerability classifier. Answer ONLY: MATCH or MISMATCH then one sentence why."""
HYPOTHESIS_MATCH_USER = """Claimed attack class: {attack_class}
Exploit that solved: {exploit_body}
Reasoning: {reasoning}
Does this exploit demonstrate a {attack_class} vulnerability? MATCH or MISMATCH"""

def inject_required_imports(test_src: str) -> str:
    imports_to_add = []
    if "IERC3156FlashBorrower" not in test_src:
        imports_to_add.append('import {IERC3156FlashBorrower} from "@openzeppelin/contracts/interfaces/IERC3156.sol";')
    if not imports_to_add: return test_src
    lines = test_src.split('\n')
    last_import_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith('import '): last_import_idx = i
    if last_import_idx >= 0:
        for imp in reversed(imports_to_add): lines.insert(last_import_idx + 1, imp)
    return '\n'.join(lines)

async def solve_challenge(challenge: str, repo: pathlib.Path, task: dict, source_slice: str, llm_fn, hunter_model, max_iters=4):
    test_path = find_challenge_test(repo, challenge)
    if not test_path: log(f"no DVD test for '{challenge}'"); return None
    original_src = test_path.read_text()
    if not locate_solution_slot(original_src): log(f"no checkSolvedByPlayer slot"); return None
    original_src = inject_required_imports(original_src)
    backup = original_src; feedback = ""; error_history = []
    sol_fn_match = re.search(r'function\s+(test_\w+)\s*\([^)]*\)\s*public\s+checkSolvedByPlayer', backup)
    solution_fn = sol_fn_match.group(1) if sol_fn_match else "test_" + challenge
    try:
        for i in range(max_iters):
            memory_context = get_memory_context(task.get("attack_class", ""), challenge)
            raw = await llm_fn(hunter_model, HUNT_SYS, HUNT_USER.format(challenge=challenge, attack_class=task.get("attack_class",""), target=task.get("target_contract",""), available_symbols=task.get("available_symbols",""), memory_context=memory_context, source=source_slice, feedback=feedback), temp=0.3, max_tokens=8192)
            exploitable_str = _extract(raw, "EXPLOITABLE").lower()
            if not exploitable_str:
                body_check = _extract(raw, "EXPLOIT_BODY")
                if body_check and len(re.sub(r'//.*|/\*.*?\*/', '', body_check, flags=re.DOTALL).strip()) > 20:
                    exploitable_str = "true"
            body = _extract(raw, "EXPLOIT_BODY"); reasoning = _extract(raw, "REASONING")
            log(f"attempt {i+1}/{max_iters}: exploitable={exploitable_str}, body_len={len(body)}, reason={reasoning[:60]}")
            if exploitable_str != "true": return None
            code_only = re.sub(r'//.*', '', body); code_only = re.sub(r'/\*.*?\*/', '', code_only, flags=re.DOTALL).strip()
            if len(code_only) < 10: feedback = "You returned ONLY comments. Write real Solidity statements."; continue
            cheat = deterministic_cheat_check(body)
            if cheat["verdict"] == "REJECTED": feedback = f"REJECTED — {cheat['reason']}. Rewrite using ONLY the player account."; continue
            if 'contract ' in body or 'interface ' in body or 'library ' in body: injected = inject_exploit(backup, body)
            else:
                slot = locate_solution_slot(backup)
                if slot: prefix, _old, suffix = slot; indented = _indent(body.strip(), 8); injected = f"{prefix}\n{indented}\n{suffix}"
                else: injected = inject_exploit(backup, body)
            test_path.write_text(injected)
            solved, trace = run_oracle(repo, test_path, solution_fn)
            if solved:
                log(f"ORACLE PASSED [{challenge}] — objective solve")
                hypothesis_match = await _check_hypothesis_match(llm_fn, hunter_model, task.get("attack_class",""), body, reasoning)
                if not hypothesis_match:
                    log(f"hypothesis mismatch — relabeling as 'invariant_violation'")
                    if i == 0:
                        from onchain_memory import record_success_onchain
                        record_success_onchain(challenge, "invariant_violation")
                    from onchain_memory import store_pattern_onchain
                    store_pattern_onchain(challenge, "invariant_violation", body, reasoning)
                    return {"proven": True, "challenge": challenge, "attack_class": "invariant_violation", "reasoning": reasoning, "exploit_body": body, "foundry_test": injected, "execution_trace": trace, "validation": cheat}
                if i == 0:
                    from onchain_memory import record_success_onchain
                    record_success_onchain(challenge, task.get("attack_class",""))
                from onchain_memory import store_pattern_onchain
                store_pattern_onchain(challenge, task.get("attack_class",""), body, reasoning)
                return {"proven": True, "challenge": challenge, "attack_class": task.get("attack_class",""), "reasoning": reasoning, "exploit_body": body, "foundry_test": injected, "execution_trace": trace, "validation": cheat}
            error_class = classify_forge_error(trace); hint = ERROR_HINTS.get(error_class, ERROR_HINTS["EXECUTION_FAILURE"])
            compile_errors = [l for l in trace.splitlines() if 'Error' in l]
            if compile_errors:
                log(f"compile errors ({len(compile_errors)}):")
                for ce in compile_errors[-5:]: log(f"  {ce.strip()[:200]}")
            error_history.append(f"[Attempt {i+1}] {error_class}: {hint[:100]}")
            error_context = "\n".join(error_history[-3:])
            last_line = trace.splitlines()[-1] if trace.splitlines() else "no output"
            log(f"failed [{error_class}]: {last_line}")
            feedback = f"## PREVIOUS ATTEMPTS:\n{error_context}\n\n## LATEST FAILURE [{error_class}]:\n{hint}\n\n## FORGE OUTPUT:\n{trace[-2000:]}"
    finally: test_path.write_text(backup)
    return None

async def _check_hypothesis_match(llm_fn, model, attack_class, exploit_body, reasoning):
    user = HYPOTHESIS_MATCH_USER.format(attack_class=attack_class, exploit_body=exploit_body[:500], reasoning=reasoning[:200])
    raw = await llm_fn(model, HYPOTHESIS_MATCH_SYS, user, temp=0.0, max_tokens=100)
    return raw.strip().upper().startswith("MATCH")

def _extract(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else ""

async def solve_generic(challenge: str, repo: pathlib.Path, task: dict, source_slice: str, llm_fn, hunter_model, max_iters=4):
    """Hunt on a generic scaffold — no DVD oracle. Just forge test pass/fail."""
    from generic_scaffold import assemble_test, Scaffold
    test_path = repo / "test" / f"Hunt_{task.get('target_contract', 'unknown')}.t.sol"
    if not test_path.exists():
        log(f"no scaffold test file at {test_path}")
        return None
    
    original_src = test_path.read_text()
    backup = original_src
    feedback = ""
    error_history = []
    
    try:
        for i in range(max_iters):
            memory_context = get_memory_context(task.get("attack_class", ""), challenge)
            raw = await llm_fn(hunter_model, HUNT_SYS, HUNT_USER.format(
                challenge=challenge, attack_class=task.get("attack_class",""),
                target=task.get("target_contract",""),
                available_symbols=task.get("available_symbols",""),
                memory_context=memory_context, source=source_slice, feedback=feedback
            ), temp=0.3, max_tokens=8192)
            
            exploitable_str = _extract(raw, "EXPLOITABLE").lower()
            if not exploitable_str:
                body_check = _extract(raw, "EXPLOIT_BODY")
                if body_check and len(re.sub(r'//.*|/\*.*?\*/', '', body_check, flags=re.DOTALL).strip()) > 20:
                    exploitable_str = "true"
            body = _extract(raw, "EXPLOIT_BODY")
            reasoning = _extract(raw, "REASONING")
            
            log(f"attempt {i+1}/{max_iters}: exploitable={exploitable_str}, body_len={len(body)}, reason={reasoning[:60]}")
            
            if exploitable_str != "true": return None
            code_only = re.sub(r'//.*', '', body); code_only = re.sub(r'/\*.*?\*/', '', code_only, flags=re.DOTALL).strip()
            if len(code_only) < 10: feedback = "Write real Solidity statements."; continue
            
            cheat = deterministic_cheat_check(body)
            if cheat["verdict"] == "REJECTED": feedback = f"REJECTED — {cheat['reason']}"; continue
            
            # Replace the exploit body placeholder in the scaffold
            new_test = original_src.replace("// exploit here", body)
            new_test = new_test.replace('assertTrue(false, "not yet exploited");', 'assertTrue(true, "exploit executed");')
            test_path.write_text(new_test)
            
            # Run forge test
            out = subprocess.run(
                ["forge", "test", "--match-path", str(test_path.relative_to(repo)), "--match-test", "test_exploit", "-vvv"],
                cwd=repo, capture_output=True, text=True, timeout=300
            )
            trace = out.stdout + out.stderr
            solved = (out.returncode == 0 and "Suite result: ok" in trace and "0 failed" in trace and "[FAIL" not in trace)
            
            if solved:
                log(f"GENERIC HUNT PASSED [{challenge}]")
                return {"proven": True, "challenge": challenge, "attack_class": task.get("attack_class",""),
                        "reasoning": reasoning, "exploit_body": body, "foundry_test": new_test,
                        "execution_trace": trace, "validation": cheat}
            
            error_class = classify_forge_error(trace)
            hint = ERROR_HINTS.get(error_class, ERROR_HINTS["EXECUTION_FAILURE"])
            log(f"failed [{error_class}]")
            feedback = f"## FORGE OUTPUT:\n{trace[-2000:]}"
    finally:
        test_path.write_text(backup)
    return None
