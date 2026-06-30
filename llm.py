import os, json, re, aiohttp, asyncio, time, pathlib, datetime
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

NV_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NV_KEY = "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"

SN_URL = "https://api.sambanova.ai/v1/chat/completions"
SN_KEY = "aa00847f-db17-461e-b725-18984b37a59e"

FTA_URL = "https://api.freetheai.xyz/v1/chat/completions"
FTA_KEY = "sta_dc76b3955da50e5632cdc2c5aca544d0069de7ffb276900d"

RECON_MODEL = "moonshotai/kimi-k2.6"
HUNTER_MODEL = "moonshotai/kimi-k2.6"

NV_FALLBACKS = ["z-ai/glm-5.1", "nvidia/nemotron-3-ultra-550b-a55b", "deepseek-ai/deepseek-v4-flash"]
SN_FALLBACKS = ["DeepSeek-V3.2", "Meta-Llama-3.3-70B-Instruct", "gemma-4-31B-it"]
FTA_FALLBACKS = ["opc/deepseek-v4-flash-free"]

_last_call = 0
_MIN_INTERVAL = 0.5

class RateLimitError(Exception):
    pass
class AllModelsFailed(Exception):
    pass

async def _rate_limit():
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < _MIN_INTERVAL:
        await asyncio.sleep(_MIN_INTERVAL - elapsed)
    _last_call = time.time()

async def _call_api(url, key, model, system, user, temp, max_tokens, provider):
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    payload = {"model": model, "messages": [{"role":"system","content":system},{"role":"user","content":user}], "max_tokens": max_tokens, "temperature": temp, "stream": False}
    if "nvidia" in url: payload["top_p"] = 1.0
    prompt_chars = len(system) + len(user)
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            data = await resp.json()
            if resp.status == 429: raise RateLimitError("429")
            if "error" in data:
                msg = data["error"]
                if isinstance(msg, dict): msg = msg.get("message", str(msg))
                if "limit" in str(msg).lower() or "exhausted" in str(msg).lower() or "capacity" in str(msg).lower(): raise RateLimitError(str(msg)[:100])
                raise RuntimeError(str(msg)[:200])
            if "choices" not in data: raise RuntimeError("No choices")
            raw = data["choices"][0]["message"]["content"]
            finish = data["choices"][0].get("finish_reason", "unknown")
            _log(provider, model, prompt_chars, raw, finish)
            return raw

def _log(provider, model, prompt_chars, raw, finish):
    log_path = pathlib.Path.home() / "hunter" / "raw_llm.log"
    with open(log_path, "a") as f:
        f.write(f"\n{'='*60}\n{datetime.datetime.now()}  provider={provider}  model={model}\n")
        f.write(f"PROMPT_CHARS={prompt_chars}  RESPONSE_LEN={len(raw) if raw else 0}  FINISH_REASON={finish}\n")
        if raw: f.write(f"RAW:\n{raw[:1500]}\n")

async def _try_tier(url, key, models, system, user, temp, max_tokens, tier_name):
    for model in models:
        try: return await _call_api(url, key, model, system, user, temp, max_tokens, tier_name)
        except RateLimitError: continue
        except Exception: continue
    return None

@retry(retry=retry_if_exception_type(RateLimitError), wait=wait_exponential(multiplier=2, min=5, max=60), stop=stop_after_attempt(5), reraise=True)
async def llm(model: str, system: str, user: str, temp: float = 0.2, max_tokens: int = 4096) -> str:
    await _rate_limit()
    try: return await _call_api(NV_URL, NV_KEY, model, system, user, temp, max_tokens, "nvidia")
    except RateLimitError: pass
    except Exception: pass
    result = await _try_tier(NV_URL, NV_KEY, [m for m in NV_FALLBACKS if m != model], system, user, temp, max_tokens, "nvidia")
    if result: return result
    result = await _try_tier(SN_URL, SN_KEY, SN_FALLBACKS, system, user, temp, max_tokens, "sambanova")
    if result: return result
    result = await _try_tier(FTA_URL, FTA_KEY, FTA_FALLBACKS, system, user, temp, max_tokens, "freetheai")
    if result: return result
    raise AllModelsFailed(f"All models failed for prompt of {len(user)} chars")

def parse_json(s: str):
    if not s: return None
    original_len = len(s)
    s = s.strip()
    try: return json.loads(s)
    except json.JSONDecodeError: pass
    fence_start = s.find("```")
    if fence_start != -1:
        inner_start = fence_start + 3
        after = s[inner_start:]
        if after.startswith("json"): inner_start += 4
        fence_end = s.find("```", inner_start)
        if fence_end != -1:
            inner = s[inner_start:fence_end].strip()
            try: return json.loads(inner)
            except json.JSONDecodeError: pass
        else:
            inner = after.strip()
            if inner.startswith("json"): inner = inner[4:].strip()
            try: return json.loads(inner)
            except json.JSONDecodeError: pass
            s = inner
    if s.startswith('[') and not s.rstrip().endswith(']'):
        last_brace = s.rfind('}')
        if last_brace > 0:
            try: return json.loads(s[:last_brace+1] + ']')
            except json.JSONDecodeError: pass
    for pattern in [r'\[.*\]', r'\{.*\}']:
        match = re.search(pattern, s, re.DOTALL)
        if match:
            try: return json.loads(match.group())
            except json.JSONDecodeError: pass
    print(f"[parse_json] FAILED | input len={original_len}", flush=True)
    return None
