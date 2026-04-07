import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# System Config
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
NEON_DSN = os.getenv("NEON_DSN")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

# Embedding Config
COLLECTION_NAME = "doc_chunks"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"  # 50MB, ringan
EMBED_SIZE = 384
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200

# Chat Config
MAX_MEMORY = 10
MODELS = [
    "nvidia/nemotron-ultra-253b-v1:free",
    "mistralai/mistral-7b-instruct:free",
    "openrouter/auto",
]

# File Support Configuration
SUPPORTED_EXTS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json",
    ".csv", ".html", ".css", ".xml", ".pdf"
}
