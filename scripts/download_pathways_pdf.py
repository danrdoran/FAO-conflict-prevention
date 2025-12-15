from pathlib import Path
import requests

# Replace with your preferred OpenKnowledge "bitstream" direct PDF link if needed.
URL = "https://openknowledge.worldbank.org/server/api/core/bitstreams/9f4c0b77-b4bd-5e8f-a6d2-2a5f3c6842e2/content"

out = Path("data/docs/Pathways for Peace.pdf")
out.parent.mkdir(parents=True, exist_ok=True)

r = requests.get(URL, timeout=120)
r.raise_for_status()
out.write_bytes(r.content)

print(f"Saved to {out.resolve()}")