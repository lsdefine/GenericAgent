import requests, json

models = ["gpt-4", "gpt-5", "gpt-5.4-mini", "claude-sonnet-4.5", "claude-opus-4.7", "gemini-2.5-pro", "gemini-3-flash"]
results = []
url = "http://127.0.0.1:8000/v1/chat/completions"

for m in models:
    payload = {
        "model": m,
        "messages": [{"role": "user", "content": "reply only pong"}],
        "stream": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        status = resp.status_code
        success = 200 <= status < 300
        error = "" if success else resp.text[:100]
        results.append({"model": m, "status": status, "success": success, "error": error})
    except Exception as e:
        results.append({"model": m, "status": 0, "success": False, "error": str(e)})

print(json.dumps(results, indent=2))
