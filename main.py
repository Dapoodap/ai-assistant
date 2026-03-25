import json, os, requests
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

API_KEY = os.getenv("OPENROUTER_API_KEY")

STATE_FILE = "state.json"
DOC_FILE = "docs.json"

def load_json(f):
    try:
        return json.load(open(f))
    except:
        return {}

def save_json(f, d):
    json.dump(d, open(f, "w"))

state = load_json(STATE_FILE)
docs = load_json(DOC_FILE)

# ================= MODEL =================
MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "mistralai/mistral-7b-instruct",
    "openrouter/auto"
]

def ask_llm(messages, model_idx=0):
    for i in range(model_idx, len(MODELS)):
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json"
                },
                json={"model": MODELS[i], "messages": messages},
                timeout=20
            )
            return r.json()["choices"][0]["message"]["content"]
        except:
            continue
    return "Model lagi sibuk"
def detect_activity_ai(text):
    prompt = f"""
    Klasifikasikan aktivitas ini jadi salah satu:
    gaming, programming, working, general

    Text: {text}

    Jawab hanya 1 kata.
    """

    result = ask_llm([{"role": "user", "content": prompt}])
    return result.strip().lower()

# ================= ACTIVITY =================
def detect_activity(text):
    t = text.lower()
    if any(k in t for k in ["game","rank","valorant","ml","pubg"]):
        return "gaming"
    if any(k in t for k in ["code","error","bug","api","python","docker"]):
        return "programming"
    return "general"

# ================= MEMORY =================
def update_memory(user, role, text):
    if user not in state:
        state[user] = {}
    mem = state[user].get("memory", [])
    mem.append({"role": role, "content": text})
    state[user]["memory"] = mem[-5:]
    save_json(STATE_FILE, state)

# ================= DOC =================
def chunk(text, size=500):
    return [text[i:i+size] for i in range(0, len(text), size)]

def search_doc(user, query):
    chunks = docs.get(user, [])
    return [c for c in chunks if any(w in c.lower() for w in query.lower().split())][:3]

# ================= REQUEST =================
class ChatReq(BaseModel):
    user_id: str
    message: str

@app.post("/chat")
def chat(req: ChatReq):
    user = req.user_id
    text = req.message

    activity = detect_activity(text)

    if activity == "general":
        activity = detect_activity_ai(text)
        
        
        
    if user not in state:
        state[user] = {}
    state[user]["activity"] = activity

    mem = state[user].get("memory", [])
    doc_ctx = "\n".join(search_doc(user, text))
    model_idx = state[user].get("model", 0)

    messages = [
    {
        "role": "system",
        "content": f"""
            Kamu adalah asisten pribadi bernama DAPOAI.

            User bernama Daffa adalah pengguna dalam sistem ini.
            Semua informasi tentang Daffa berasal dari konteks yang diberikan di bawah.

            Konteks user:
            - Aktivitas saat ini: {activity}
            - Dokumen: {doc_ctx}

            Aturan:
            - Anggap Daffa sebagai user dalam sistem, bukan orang di dunia nyata
            - Jangan gunakan pengetahuan luar tentang Daffa
            - Jika ditanya "Daffa lagi apa", jawab berdasarkan aktivitas di atas
            - Jangan menolak menjawab dengan alasan tidak tahu
            - Jawab singkat, natural, dan ramah dalam bahasa Indonesia
            """
                }
            ] + mem + [{"role": "user", "content": text}]

    reply = ask_llm(messages, model_idx)

    update_memory(user, "user", text)
    update_memory(user, "assistant", reply)

    return {"reply": reply}