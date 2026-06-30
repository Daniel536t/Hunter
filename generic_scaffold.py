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
    bytecode: str = ""

@dataclass
class Scaffold:
    test_name: str
    imports: str
    declarations: str
    deploy_code: str
    abi_summary: str
    target_contracts: list
    solc_version: str = "0.8.20"
    compiles: bool = False
    test_file_path: pathlib.Path = None

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
        if any(x in src_path.lower() for x in ["lib/forge-std", "node_modules", "/mocks/", "/test/", "/interfaces/"]): continue
        has_constructor = any(e.get("type") == "constructor" for e in abi)
        has_state_changing = any(e.get("type") == "function" and e.get("stateMutability") not in ("view", "pure") for e in abi)
        if not has_constructor and not has_state_changing: continue
        ctor_inputs = []
        for entry in abi:
            if entry.get("type") == "constructor": ctor_inputs = entry.get("inputs", []); break
        if src_path:
            src_file = repo / src_path
            if src_file.exists():
                src_text = src_file.read_text(errors="ignore")
                ctor_match = re.search(r'constructor\s*\(([^)]*)\)', src_text)
                if ctor_match and ctor_match.group(1).strip():
                    src_args = []
                    for arg in ctor_match.group(1).split(','):
                        arg = arg.strip(); parts = arg.split()
                        if len(parts) >= 2: src_args.append({"type": parts[-2], "name": parts[-1].lstrip('_')})
                    if src_args: ctor_inputs = src_args
        contracts[name] = ContractInfo(name=name, source_path=src_path, abi=abi, constructor_inputs=ctor_inputs, bytecode=data.get("bytecode",{}).get("object",""))
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

SCAFFOLD_TEMPLATE = """// SPDX-License-Identifier: MIT
pragma solidity {solc_version};

{imports}

contract {test_name} is Test {{
{declarations}
    address deployer = makeAddr("deployer");
    address attacker = makeAddr("attacker");

    function setUp() public {{
{deploy_code}
    }}

    function test_exploit() public {{
        vm.startPrank(attacker);
{exploit_body}
        vm.stopPrank();
{assertion}
    }}
}}
"""

def generate_scaffold(repo: pathlib.Path, target_contract: str) -> Scaffold | None:
    if not forge_build(repo): return None
    contracts = extract_contracts(repo)
    if target_contract not in contracts:
        print(f"[scaffold] '{target_contract}' not found. Available:")
        for name in sorted(contracts.keys()): print(f"  {name}")
        return None
    target = contracts[target_contract]
    target_dir = pathlib.Path(target.source_path).parent if target.source_path else None
    scope = {target_contract: target}
    for name, ci in contracts.items():
        if name == target_contract: continue
        ci_dir = pathlib.Path(ci.source_path).parent if ci.source_path else None
        if target_dir and ci_dir and str(target_dir) == str(ci_dir): scope[name] = ci
    solc_version = "0.8.20"
    ft = repo / "foundry.toml"
    if ft.exists():
        ftxt = ft.read_text()
        vm = re.search(r'solc(?:_version)?\s*=\s*["\']([\d.]+)["\']', ftxt)
        if vm: solc_version = vm.group(1)
    if target.source_path:
        tf = repo / target.source_path
        if tf.exists():
            stxt = tf.read_text(errors="ignore")
            vm = re.search(r'pragma solidity [=^]*([\d.]+)', stxt)
            if vm: solc_version = vm.group(1)
    imports = ['import "forge-std/Test.sol";']
    for name, ci in scope.items():
        if ci.source_path: imports.append(f'import {{{name}}} from "{ci.source_path}";')
    declarations = [f"    {name} {name.lower()};" for name in scope]
    deploy_lines = ["        vm.startPrank(deployer);"]
    no_ctor = [n for n, c in scope.items() if not c.constructor_inputs]
    has_ctor = [n for n, c in scope.items() if c.constructor_inputs]
    for name in no_ctor: deploy_lines.append(f"        {name.lower()} = new {name}();")
    for name in has_ctor:
        ci = scope[name]; args = []
        for inp in ci.constructor_inputs:
            arg_type = inp["type"]; arg_name = inp.get("name", "").lower()
            if arg_type == "address":
                matched = None
                for sname in scope:
                    if sname.lower() in arg_name or arg_name in sname.lower(): matched = sname; break
                    if "token" in arg_name and "token" in sname.lower(): matched = sname; break
                if matched: args.append(f"address({matched.lower()})")
                else: args.append(f'makeAddr("{inp.get("name", "param")}")')
            elif arg_type.startswith("uint"): args.append("0")
            elif arg_type == "bool": args.append("false")
            else:
                if arg_type in scope: args.append(scope[arg_type].name.lower())
                else: args.append(f'makeAddr("{inp.get("name", "param")}")')
        deploy_lines.append(f"        {name.lower()} = new {name}({', '.join(args)});")
    deploy_lines.append("        vm.stopPrank();")
    summaries = [abi_summary(scope[name]) for name in scope]
    imports_str = "\n".join(imports)
    declarations_str = "\n".join(declarations)
    deploy_str = "\n".join(deploy_lines)
    all_summaries = "\n\n".join(summaries)
    scaf = Scaffold(test_name=f"Hunt_{target_contract}", imports=imports_str, declarations=declarations_str, deploy_code=deploy_str, abi_summary=all_summaries, target_contracts=list(scope.keys()), solc_version=solc_version)
    test_dir = repo / "test"; test_dir.mkdir(exist_ok=True, parents=True)
    test_path = test_dir / f"{scaf.test_name}.t.sol"
    code = assemble_test(scaf, "// scaffold check", "assertTrue(true, 'scaffold compiles');")
    test_path.write_text(code)
    out = subprocess.run(["forge", "build", str(test_path)], cwd=repo, capture_output=True, text=True, timeout=300)
    scaf.compiles = out.returncode == 0
    scaf.test_file_path = test_path
    if not scaf.compiles: print(f"[scaffold] Compile errors:\n{(out.stdout + out.stderr)[-2000:]}")
    return scaf

def assemble_test(scaf: Scaffold, exploit_body: str, assertion: str = "") -> str:
    return SCAFFOLD_TEMPLATE.format(solc_version=getattr(scaf, "solc_version", "0.8.20"), test_name=scaf.test_name, imports=scaf.imports, declarations=scaf.declarations, deploy_code=scaf.deploy_code, exploit_body=_indent(exploit_body or "// exploit goes here", 8), assertion=_indent(assertion or "assertTrue(false, \"not yet exploited\");", 8))

def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + l if l.strip() else l for l in text.splitlines())
