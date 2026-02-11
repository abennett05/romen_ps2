from colorama import Fore, Style
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import shutil
import uuid

# local modules
import system
from system import *

#  - - - CONFIGURABLE - - -
WEB_APP_PATH = '../romen-ps2-front/dist/index.html' # Routes to the index.html that houses our React app.
HOST = "0.0.0.0"
PORT = 8000
#  - - - CONFIGURABLE - - -

# - - - APP SETUP - - -
app = FastAPI()

# Development stuff leave commented out
"""origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]

# Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)"""

assets_path = os.path.join(os.path.dirname(WEB_APP_PATH), "assets")
img_path = os.path.join(os.path.dirname(WEB_APP_PATH), "img")
if os.path.exists(assets_path):
    app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
if os.path.exists(img_path):
    app.mount("/img", StaticFiles(directory=img_path), name="img")

# - - - APP SETUP - - -

JOB_RESULT = {}

def process_upload_wrapper(temp_path: str, job_id: str):
    try:
        result = system.ProcessUpload(temp_path)

        JOB_RESULT[job_id] = result
    except Exception as e:
        os.remove(temp_path)
        JOB_RESULT[job_id] = {"status": "error", "message": str(e)}

@app.post("/upload")
def upload_game(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    print(f"[API] Receiving file: {file.filename}")

    # 1. Save file to uploads dir   
    temp_path = os.path.join(system.CONFIG.UPLOADS_PATH, file.filename)
    with open(temp_path, 'wb') as buffer:
        shutil.copyfileobj(file.file, buffer)

    job_id = str(uuid.uuid4())
    JOB_RESULT[job_id] = {"status": "processing"}

    background_tasks.add_task(process_upload_wrapper, temp_path, job_id)
    return {"job_id": job_id}

@app.get("/job/{job_id}")
def get_job_status(job_id: str):
    result = JOB_RESULT.get(job_id)

    if result:
        return result
    return {"status": "processing"}

@app.get("/library")
def get_library():
    response = system.get_library()
    print(response)
    return response

@app.delete("/library/{serial}")
def delete_game(serial: str):
    success = system.remove_from_library(serial)
    
    if success:
        return {"status": "success", "message": "Game removed"}
    else:
        # Return 500 or 404 depending on logic, keeping it simple here
        return {"status": "error", "message": "Failed to remove game"}

@app.get("/device")
def get_device():
    try:
        return system.get_storage_device(system.CONFIG.LIB_PATH)
    except Exception as e:
        return {"status" : "error" , "message": "Failed to get storage device"}

@app.post("/set-device")
def set_device(path: str):
    if (system.VerifyDir(path)[0]):
        return system.set_library_path(path)
    return {"status" : "error" , "message": "Failed to set storage device"}

# Serve actual web app
@app.get("/{full_path:path}")
def serve_app():
    if os.path.exists(WEB_APP_PATH):
        return FileResponse(WEB_APP_PATH)
    return {"error": "Frontend build not found. Verify that build exists & is routed properly."}

    
if __name__ == "__main__":
    # system checks
    system.CheckDatabases()
    uvicorn.run(app, host=HOST, port=PORT)
    pass