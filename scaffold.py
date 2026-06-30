import json, subprocess, pathlib, re
from dataclasses import dataclass

def forge_build(repo: pathlib.Path) -> bool:
    out = subprocess.run(["forge", "build", "--build-info"], cwd=repo, capture_output=True, text=True, timeout=600)
    return out.returncode == 0

@dataclass
class ContractInfo:
    name: str
    source_path: str
    abi: list
    constructor_inputs: list

def extract_contracts(repo: pathlib.Path) -> dict[str, ContractInfo]:
    out_dir = repo / "out"
    contracts: dict[str, ContractInfo] = {}
    for artifact in out_dir.rglob("*.json"):
        if "build-info" in str(artifact): continue
        try: data = json.loads(artifact.read_text())
        except: continue
        abi = data.get("abi")
        if not abi: continue
        name = artifact.stem
        src_path = ""
        meta = data.get("metadata")
        if isinstance(meta, dict):
            targets = meta.get("settings", {}).get("compilationTarget", {})
            if targets: src_path = next(iter(targets.keys()), "")
        if not src_path:
            ast = data.get("ast", {})
            src_path = ast.get("absolutePath", "")
        if any(x in src_path.lower() for x in ["lib/forge-std", "node_modules", "/mocks/"]): continue
        ctor_inputs = []
        for entry in abi:
            if entry.get("type") == "constructor":
                ctor_inputs = entry.get("inputs", [])
                break
        contracts[name] = ContractInfo(name=name, source_path=src_path, abi=abi, constructor_inputs=ctor_inputs)
    return contracts

def abi_summary(ci: ContractInfo) -> str:
    lines = [f"contract {ci.name}  // {ci.source_path}"]
    for e in ci.abi:
        if e.get("type") == "function":
            ins = ",".join(f"{i['type']} {i.get('name','')}".strip() for i in e.get("inputs", []))
            outs = ",".join(o["type"] for o in e.get("outputs", []))
            mut = e.get("stateMutability", "")
            sig = f"  function {e['name']}({ins})"
            if mut in ("view", "pure", "payable"): sig += f" {mut}"
            if outs: sig += f" returns ({outs})"
            lines.append(sig)
        elif e.get("type") == "constructor":
            ins = ",".join(f"{i['type']} {i.get('name','')}".strip() for i in e.get("inputs", []))
            lines.append(f"  constructor({ins})")
    return "\n".join(lines)

def find_existing_setup(repo: pathlib.Path, target: str) -> str | None:
    best, best_score = None, -1
    for f in repo.rglob("*.t.sol"):
        if f.is_dir(): continue
        if "lib/forge-std" in str(f): continue
        txt = f.read_text(errors="ignore")
        if target not in txt: continue
        block = _extract_function(txt, "setUp")
        if not block: continue
        score = txt.count(target)
        if score > best_score: best, best_score = block, score
    return best

def _extract_function(src: str, fn_name: str) -> str | None:
    m = re.search(rf"function\s+{fn_name}\s*\([^)]*\)[^{{]*{{", src)
    if not m: return None
    start = m.end() - 1
    depth, i = 0, start
    while i < len(src):
        if src[i] == "{": depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0: return src[start + 1:i].strip()
        i += 1
    return None

def find_declarations(setup_src: str, contracts: dict) -> str:
    decls = []
    for name in contracts:
        m = re.search(rf"(\w+)\s*=\s*(?:new\s+)?{name}\s*[\(;]", setup_src)
        if m: decls.append(f"    {name} {m.group(1)};")
    return "\n".join(dict.fromkeys(decls))

def use_existing_dvd_test(repo: pathlib.Path, target_contract: str) -> dict | None:
    for src_file in repo.rglob(f"src/**/{target_contract}.sol"):
        if src_file.is_dir(): continue
        challenge_dir = src_file.parent.name
        for test_file in repo.rglob(f"test/{challenge_dir}/*.t.sol"):
            if test_file.is_dir(): continue
            src = test_file.read_text()
            m = re.search(r'(function\s+test_\w+\s*\([^)]*\)\s*public\s+\w*\s*checkSolvedByPlayer\s*\{)(.*?)(\n\s*\})', src, re.DOTALL)
            if not m: continue
            before = src[:m.start(2)]
            after = src[m.end(2):]
            return {"test_file_path": test_file, "full_source": src, "before_body": before, "after_body": after, "challenge": challenge_dir}
    return None

def assemble_dvd_exploit(dvd_test: dict, exploit_body: str) -> str:
    return dvd_test["before_body"] + exploit_body + dvd_test["after_body"]

def extract_dvd_symbols(test_src: str) -> str:
    symbols = []
    for m in re.finditer(r'^\s*(\w+(?:\.\w+)?)\s+(?:public\s+|private\s+|internal\s+|constant\s+)*(\w+)\s*[=;]', test_src, re.MULTILINE):
        var_type, var_name = m.group(1), m.group(2)
        skip = {"is", "public", "private", "internal", "constant", "Test", "setUp", "test", "pragma", "import", "contract", "function", "modifier", "if", "for", "return", "monitorContract", "it", "ownership"}
        if var_name in skip: continue
        if var_type in ("uint256", "address", "bytes32"): symbols.append(f"  {var_type} {var_name}")
        elif var_type[0].isupper(): symbols.append(f"  {var_type} {var_name}")
    return "\n".join(dict.fromkeys(symbols)) if symbols else "(no symbols extracted)"
