import io, hashlib, pathlib, sqlite3, datetime, requests

PINATA_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySW5mb3JtYXRpb24iOnsiaWQiOiI3NzIxYjAwZC1lNThlLTRhNTQtYjQ0Yy0wMTY0YTEwN2U3ZDIiLCJlbWFpbCI6ImRhbmllbGJyaWdodGVuNEBnbWFpbC5jb20iLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwicGluX3BvbGljeSI6eyJyZWdpb25zIjpbeyJkZXNpcmVkUmVwbGljYXRpb25Db3VudCI6MSwiaWQiOiJGUkExIn0seyJkZXNpcmVkUmVwbGljYXRpb25Db3VudCI6MSwiaWQiOiJOWUMxIn1dLCJ2ZXJzaW9uIjoxfSwibWZhX2VuYWJsZWQiOmZhbHNlLCJzdGF0dXMiOiJBQ1RJVkUifSwiYXV0aGVudGljYXRpb25UeXBlIjoic2NvcGVkS2V5Iiwic2NvcGVkS2V5S2V5IjoiNjcxNmY4NWU0YzBiYWMzYWJjMWIiLCJzY29wZWRLZXlTZWNyZXQiOiIyYWZmYTcyZWRmNGE2YmQwMmUzMDFiMDgyMWQzYTIxZGNlZTdlZWU1ZDE1YzU4M2I0NzIxZjgyMmRkZDJlNjkzIiwiZXhwIjoxODE0MTQ3NDU5fQ.1ylx8oV4G1KvouB4657yYDtnGZtHFs34uLgR0xaE9Vc"
PINATA_URL = "https://api.pinata.cloud/pinning/pinFileToIPFS"
GATEWAY_URL = "https://gateway.pinata.cloud/ipfs/"

def upload_to_ipfs(content, filename):
    headers = {"Authorization": f"Bearer {PINATA_JWT}"}
    file_obj = io.BytesIO(content.encode("utf-8"))
    files = {"file": (filename, file_obj, "text/plain")}
    try:
        r = requests.post(PINATA_URL, files=files, headers=headers, timeout=30)
        data = r.json()
        return data.get("IpfsHash")
    except Exception as e:
        print(f"  [ipfs] Upload failed: {e}", flush=True)
        return None

def retrieve_from_ipfs(cid):
    try:
        r = requests.get(f"{GATEWAY_URL}{cid}", timeout=30)
        return r.text if r.status_code == 200 else None
    except Exception as e:
        print(f"  [ipfs] Retrieve failed for {cid}: {e}", flush=True)
        return None
