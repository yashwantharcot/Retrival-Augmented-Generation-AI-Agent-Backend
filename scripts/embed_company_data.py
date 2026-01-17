import requests
from bs4 import BeautifulSoup
import openai
from pymongo import MongoClient
import os

# --- CONFIG ---
COMPANY_URL = "https://www.dealdox.io/"
MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DB_NAME = "dev_db"
COLLECTION_NAME = "company_cpq_embeddings"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBED_MODEL = "text-embedding-3-small"

openai.api_key = OPENAI_API_KEY

# --- SCRAPE WEBSITE ---
def scrape_website(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    texts = []
    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "li"]):
        text = tag.get_text(strip=True)
        if text:
            texts.append(text)
    return texts

# --- EMBED TEXTS ---
def embed_texts_openai(texts, model):
    embeddings = []
    for text in texts:
        try:
            resp = openai.embeddings.create(input=text, model=model)
            emb = resp.data[0].embedding
            embeddings.append(emb)
        except Exception as e:
            embeddings.append([])
    return embeddings

# --- STORE IN MONGODB ---
def store_embeddings(texts, embeddings, db_name, collection_name):
    client = MongoClient(MONGO_URI)
    db = client[db_name]
    collection = db[collection_name]
    docs = []
    for text, emb in zip(texts, embeddings):
        docs.append({"text": text, "embedding": emb})
    collection.insert_many(docs)
    # ...existing code...

if __name__ == "__main__":
    texts = scrape_website(COMPANY_URL)
    embeddings = embed_texts_openai(texts, EMBED_MODEL)
    store_embeddings(texts, embeddings, DB_NAME, COLLECTION_NAME)
