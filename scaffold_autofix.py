import re, pathlib, subprocess
from generic_scaffold import (extract_contracts, forge_build, assemble_test, Scaffold, abi_summary, _indent)

def extract_error_types(error_output: str) -> dict[str, str]:
    fixes = {}
    for match in re.finditer(r'Invalid implicit conversion from address to contract (\w+) requested', error_output, re.MULTILINE):
        fixes[match.group(1)] = match.group(1)
    for match in re.finditer(r'Invalid implicit conversion from contract (\w+) to address requested', error_output, re.MULTILINE):
        fixes[match.group(1)] = f"address_cast_{match.group(1)}"
    return fixes

def fix_constructor_args(code: str, error_output: str, scope: dict) -> str:
    fixes = extract_error_types(error_output)
    for contract_type, fix_type in fixes.items():
        for var_name, ci in scope.items():
            if ci.name == contract_type or ci.name == fix_type.replace('address_cast_', ''):
                if fix_type.startswith('address_cast_'):
                    code = re.sub(rf'new {contract_type}\({var_name.lower()}\)', f'new {contract_type}(address({var_name.lower()}))', code)
                    code = re.sub(rf'({var_name.lower()})([,)])', f'address({var_name.lower()})\\2', code)
                else:
                    code = re.sub(rf'new {contract_type}\(makeAddr\("[^"]+"\)\)', f'new {contract_type}({var_name.lower()})', code)
                    code = re.sub(rf'new {contract_type}\(address\((\w+)\)\)', f'new {contract_type}(\\1)', code)
                break
    return code

def generate_scaffold_autofix(repo: pathlib.Path, target_contract: str, max_retries: int = 3) -> Scaffold | None:
    if not forge_build(repo): return None
    contracts = extract_contracts(repo)
    if target_contract not in contracts:
        print(f"[scaffold] '{target_contract}' not found.")
        return None
    target = contracts[target_contract]
    target_dir = pathlib.Path(target.source_path).parent if target.source_path else None
    scope = {target_contract: target}
    for name, ci in contracts.items():
        if name == target_contract: continue
        ci_dir = pathlib.Path(ci.source_path).parent if ci.source_path else None
        if target_dir and ci_dir and str(target_dir) == str(ci_dir): scope[name] = ci
    for name, ci in list(scope.items()):
        for inp in ci.constructor_inputs:
            arg_type = inp.get("type", "")
            if arg_type not in ("address", "uint256", "uint8", "bool", "string", "bytes", "bytes32", ""):
                if arg_type in contracts and arg_type not in scope: scope[arg_type] = contracts[arg_type]
    solc_version = "0.8.20"
    ft = repo / "foundry.toml"
    if ft.exists():
        vm = re.search(r'solc(?:_version)?\s*=\s*["\']([\d.]+)["\']', ft.read_text())
        if vm: solc_version = vm.group(1)
    if target.source_path:
        tf = repo / target.source_path
        if tf.exists():
            vm = re.search(r'pragma solidity [=^]*([\d.]+)', tf.read_text(errors="ignore"))
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
    scaf = Scaffold(test_name=f"Hunt_{target_contract}", imports="\n".join(imports), declarations="\n".join(declarations), deploy_code="\n".join(deploy_lines), abi_summary="\n\n".join(summaries), target_contracts=list(scope.keys()), solc_version=solc_version)
    test_dir = repo / "test"; test_dir.mkdir(exist_ok=True, parents=True)
    test_path = test_dir / f"{scaf.test_name}.t.sol"
    for attempt in range(max_retries):
        code = assemble_test(scaf, "// scaffold check", "assertTrue(true, 'scaffold compiles');")
        if attempt > 0 and error_output: code = fix_constructor_args(code, error_output, scope)
        test_path.write_text(code)
        out = subprocess.run(["forge", "build", str(test_path)], cwd=repo, capture_output=True, text=True, timeout=300)
        raw_output = out.stdout + out.stderr
        error_lines = [l for l in raw_output.splitlines() if re.search(r'Error \(\d+\):', l)]
        error_output = '\n'.join(error_lines) if error_lines else raw_output[-2000:]
        if out.returncode == 0:
            scaf.compiles = True; scaf.test_file_path = test_path
            print(f"[scaffold] Compiles after {attempt + 1} attempt(s)"); return scaf
        print(f"[scaffold] Attempt {attempt + 1}: {len(error_lines)} errors")
        for el in error_lines[:3]: print(f"  {el.strip()[:150]}")
    print(f"[scaffold] Failed after {max_retries} attempts")
    scaf.compiles = False; scaf.test_file_path = test_path; return scaf
