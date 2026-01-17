#app/db/change_stream.py
import threading
import time
from app.db.mongo import client, db, source_cols
from app.core.chunker import record_to_chunks
from app.core.embeddings import get_query_embedding
from app.config import TARGET_COLLECTION

target_col = db[TARGET_COLLECTION]

def is_replica_set(client):
    try:
        return client.admin.command("ismaster").get("setName") is not None
    except Exception as e:
        print(f"⚠️ Could not check replica set: {e}")
        return False

def embed_chunk_and_update(doc):
    chunks = record_to_chunks(doc)
    for idx, chunk in enumerate(chunks):
        embedding = get_query_embedding(chunk)
        target_col.update_one(
            {"_id": f"{doc['_id']}_{idx}"},
            {"$set": {"embedding": embedding, "chunk": chunk, "parent_id": doc["_id"]}},
            upsert=True
        )
        print(f"🧠 [LOG] Embedded and updated chunk for _id: {doc['_id']}_{idx}")

def watch_changes():
    if not is_replica_set(client):
        print("❌ MongoDB is not running as a replica set. Change streams will not work.")
        return
    print("🔄 Watching MongoDB for live updates in dd_accounts, dd_opportunities, and dd_contacts...")
    def watch_one_collection(col):
        print(f"[WATCHER] Starting watcher for collection: {col.name}")
        while True:
            try:
                with col.watch(full_document='updateLookup') as stream:
                    print(f"[WATCHER] Listening for changes in: {col.name}")
                    for change in stream:
                        print(f"[WATCHER] Change detected in {col.name}: {change}")
                        op = change["operationType"]
                        full_doc = change.get("fullDocument")
                        if op in ["insert", "update", "replace"]:
                            if full_doc:
                                full_doc["_source_collection"] = col.name
                                embed_chunk_and_update(full_doc)
                        else:
                            print(f"⚠️ Unhandled change type: {op}")
            except Exception as e:
                print(f"❌ Error in watch_changes for {col.name}: {e}. Restarting watcher in 5 seconds...")
                time.sleep(5)
    for col in source_cols:
        threading.Thread(target=watch_one_collection, args=(col,), daemon=True).start()
