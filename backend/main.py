import os
import json
import time
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import httpx
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

# ====== CONFIG ======
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DATA_DIR = Path("data")
CHATS_DIR = DATA_DIR / "chats"
CHATS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()

# NOTE: Open CORS is acceptable for local development/demos.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====== MODELS ======
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str
    message: str
    conversationId: str
    webSearch: bool = False
    memoryOn: bool = True

class Conversation(BaseModel):
    id: str
    updatedAt: float
    messages: List[Message]

# ====== FILE UTILS ======
def atomic_write_json(path: Path, data: dict):
    """
    Atomically write JSON to disk to prevent corruption.
    """
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as tmp:
        json.dump(data, tmp, indent=2)
        tmp_path = tmp.name
    shutil.move(tmp_path, path)

# ====== SEARCH ENGINE (DDG Lite) ======
async def perform_search(query: str) -> Optional[str]:
    """
    DuckDuckGo Lite HTML scraper.
    NOTE: This is brittle and intended for demo purposes only.
    """
    print(f"🕵️  System Search Query: '{query}'")

    ua = UserAgent()
    headers = {
        "User-Agent": ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://html.duckduckgo.com/",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers=headers,
            )

            soup = BeautifulSoup(resp.text, "html.parser")
            results = []

            for result in soup.select(".result")[:5]:
                title_tag = result.select_one(".result__a")
                snippet_tag = result.select_one(".result__snippet")

                if title_tag and snippet_tag:
                    title = title_tag.get_text(strip=True)
                    url = title_tag.get("href", "")
                    snippet = snippet_tag.get_text(strip=True)

                    results.append(
                        f"Title: {title}\nURL: {url}\nSummary: {snippet}"
                    )

            return "\n\n".join(results) if results else None

        except Exception as e:
            print(f"❌ Search error: {e}")
            return None

# ====== TOOLS ======
search_tool_def = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the internet for current events, news, or facts.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"}
            },
            "required": ["query"]
        }
    }
}

# ====== HELPERS ======
def load_conversation(cid: str) -> Conversation:
    path = CHATS_DIR / f"{cid}.json"
    if path.exists():
        try:
            return Conversation(**json.loads(path.read_text()))
        except Exception:
            pass
    return Conversation(id=cid, updatedAt=time.time(), messages=[])

def save_conversation(conv: Conversation):
    conv.updatedAt = time.time()
    path = CHATS_DIR / f"{conv.id}.json"
    atomic_write_json(path, conv.model_dump())

# ====== ROUTES ======
@app.get("/api/history")
async def get_history():
    chats = []
    for f in CHATS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            first_user = next(
                (m["content"] for m in data["messages"] if m["role"] == "user"),
                "New Conversation"
            )
            chats.append({
                "id": data["id"],
                "updatedAt": data.get("updatedAt", 0),
                "title": first_user[:40] + "..."
            })
        except Exception:
            continue

    return {"history": sorted(chats, key=lambda x: x["updatedAt"], reverse=True)}

@app.get("/api/history/{id}")
async def get_chat(id: str):
    path = CHATS_DIR / f"{id}.json"
    if not path.exists():
        raise HTTPException(404, "Chat not found")
    return {"conversation": json.loads(path.read_text())}

@app.get("/api/models")
async def get_models():
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{OLLAMA_BASE}/api/tags")
            return {"models": resp.json().get("models", [])}
        except Exception:
            return {"models": []}

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    conv = load_conversation(req.conversationId)

    conv.messages.append(Message(role="user", content=req.message))

    context_msgs = conv.messages if req.memoryOn else [conv.messages[-1]]
    context_data = [m.model_dump() for m in context_msgs]
    tools = [search_tool_def] if req.webSearch else []

    async def stream_generator():
        client = httpx.AsyncClient(timeout=60.0)

        try:
            init_resp = await client.post(
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": req.model,
                    "messages": context_data,
                    "stream": False,
                    "tools": tools,
                },
            )

            init_json = init_resp.json()
            final_messages = list(context_data)

            if init_json.get("message", {}).get("tool_calls"):
                tool_call = init_json["message"]["tool_calls"][0]

                if tool_call["function"]["name"] == "web_search":
                    query = tool_call["function"]["arguments"]["query"]

                    yield json.dumps({"type": "status", "content": f"🔍 Searching: {query}..."}) + "\n"

                    final_messages.append(init_json["message"])

                    search_result = await perform_search(query)
                    tool_content = f"Results:\n{search_result}" if search_result else "Search failed."

                    final_messages.append({
                        "role": "tool",
                        "content": tool_content,
                    })

            async with client.stream(
                "POST",
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": req.model,
                    "messages": final_messages,
                    "stream": True,
                },
            ) as stream_resp:

                full_text = ""

                async for line in stream_resp.aiter_lines():
                    if not line:
                        continue

                    data = json.loads(line)

                    if "message" in data and "content" in data["message"]:
                        chunk = data["message"]["content"]
                        full_text += chunk
                        yield json.dumps({"type": "chunk", "content": chunk}) + "\n"

                    if data.get("done"):
                        conv.messages.append(
                            Message(role="assistant", content=full_text)
                        )
                        save_conversation(conv)

        except Exception as e:
            yield json.dumps({"type": "error", "error": str(e)}) + "\n"

        finally:
            await client.aclose()

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
