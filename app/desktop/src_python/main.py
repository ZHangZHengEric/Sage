import os
import sys
import asyncio
import logging

# 1. Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "app"))

# 2. Set environment variables for local desktop mode
data_dir = os.path.join(current_dir, "data")
os.makedirs(data_dir, exist_ok=True)

os.environ["DB_TYPE"] = "file"
os.environ["DB_PATH"] = os.path.join(data_dir, "sage_desktop.db")
os.environ["LOG_LEVEL"] = "INFO"
os.environ["ENABLE_REDIS_LOCK"] = "False" # Disable Redis
os.environ["ENABLE_JAEGER"] = "False" # Disable Jaeger
os.environ["S3_ENDPOINT"] = "local" # Dummy
os.environ["S3_ACCESS_KEY"] = "local" # Dummy
os.environ["S3_SECRET_KEY"] = "local" # Dummy
os.environ["S3_BUCKET_Name"] = "local" # Dummy

# 3. Monkeypatching
from app.server.core.client import s3
from app.desktop.src_python.adapters.local_storage import upload_kdb_file, init_s3_client, close_s3_client

# Patch S3
s3.upload_kdb_file = upload_kdb_file
s3.init_s3_client = init_s3_client
s3.close_s3_client = close_s3_client

# Patch Vector Store
# We need to patch the class itself or where it is used.
from app.server.services.knowledge_base.adapter import es_vector_store
from app.desktop.src_python.adapters.local_vector_store import LocalVectorStore

es_vector_store.EsVectorStore = LocalVectorStore

# 4. Start Server
from app.server.main import create_fastapi_app
import uvicorn

app = create_fastapi_app()

if __name__ == "__main__":
    # Get port from environment or default to random/8000
    # In Tauri sidecar, we might want to let the OS choose a port or receive it.
    # For now, let's bind to 0 (random) and print it, or use a fixed port for testing.
    # Tauri sidecar usually expects the process to run.
    # If we use a fixed port, we need to make sure it's free.
    port = int(os.environ.get("PORT", 12345))
    
    print(f"Starting Sage Desktop Server on port {port}...")
    uvicorn.run(app, host="127.0.0.1", port=port)
