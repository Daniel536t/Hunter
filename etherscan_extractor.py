import requests, json, time, pathlib, re
from dataclasses import dataclass

NETWORKS = {
    "ethereum": {"api": "https://api.etherscan.io/api"},
    "base": {"api": "https://api.basescan.org/api"},
    "arbitrum": {"api": "https://api.arbiscan.io/api"},
    "optimism": {"api": "https://api-optimistic.etherscan.io/api"},
    "polygon": {"api": "https://api.polygonscan.com/api"},
    "bsc": {"api": "https://api.bscscan.com/api"},
    "avalanche": {"api": "https://api.snowtrace.io/api"},
}

_last_call = 0; _MIN_INTERVAL = 0.3

def _rate_limit():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _MIN_INTERVAL: time.sleep(_MIN_INTERVAL - elapsed)
    _last_call = time.time()

@dataclass
class ContractInfo:
    address: str; name: str; network: str; abi: list; source_code: str
    is_proxy: bool = False; implementation_address: str = ""

def get_contract(address: str, network: str = "ethereum") -> ContractInfo | None:
    if network not in NETWORKS: return None
    api_url = NETWORKS[network]["api"]
    _rate_limit()
    abi_resp = requests.get(api_url, params={"module":"contract","action":"getabi","address":address}, timeout=15)
    abi_data = abi_resp.json()
    if abi_data.get("status") != "1": return None
    abi = json.loads(abi_data["result"])
    _rate_limit()
    source_resp = requests.get(api_url, params={"module":"contract","action":"getsourcecode","address":address}, timeout=15)
    source_data = source_resp.json()
    if source_data.get("status") != "1": return None
    contract_data = source_data["result"][0]
    name = contract_data.get("ContractName", "Unknown")
    source = contract_data.get("SourceCode", "")
    is_proxy = bool(int(contract_data.get("Proxy", "0")))
    impl = contract_data.get("Implementation", "")
    if source.startswith("{{") or source.startswith("[{"):
        try:
            parts = json.loads(source)
            if isinstance(parts, dict) and "sources" in parts: source = "\n\n".join(f"// {k}\n{v.get('content','')}" for k,v in parts["sources"].items())
            elif isinstance(parts, list): source = "\n\n".join(f"// {s.get('name','')}\n{s.get('content','')}" for s in parts)
        except: pass
    return ContractInfo(address=address, name=name, network=network, abi=abi, source_code=source, is_proxy=is_proxy, implementation_address=impl)
