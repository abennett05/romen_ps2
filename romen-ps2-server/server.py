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
import updates
import version

#  - - - CONFIGURABLE - - -
# Routes to the index.html that houses our React app. The packaged release ships
# the build next to server.py; a repo checkout keeps it in the frontend folder.
WEB_APP_CANDIDATES = [
    './dist/index.html',
    '../romen-ps2-front/dist/index.html',
]
HOST = "0.0.0.0"
PORT = 8000
#  - - - CONFIGURABLE - - -

_here = os.path.dirname(os.path.abspath(__file__))
WEB_APP_PATH = next(
    (os.path.join(_here, c) for c in WEB_APP_CANDIDATES if os.path.exists(os.path.join(_here, c))),
    os.path.join(_here, WEB_APP_CANDIDATES[0]),
)

# - - - APP SETUP - - -
app = FastAPI()

# Development stuff leave commented out

# Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    try:
        with open(temp_path, 'wb') as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        print(f"[API] Transfer interrupted or failed: {e}")

        if os.path.exists(temp_path):
            os.remove(temp_path)
            print(f"[API] Clean up partial file: {temp_path}")
        return {"status": "error", "message": "Upload cancelled."}

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
    return response

@app.delete("/library/clear")
def clear_library():
    success = system.remove_all_from_library()

    if success:
        return {"status": "success", "message": "Library cleared"}
    else:
        # Return 500 or 404 depending on logic, keeping it simple here
        return {"status": "error", "message": "Failed to clear library"}


@app.delete("/library/{serial}")
def delete_game(serial: str):
    success = system.remove_from_library(serial)
    
    if success:
        return {"status": "success", "message": "Game removed"}
    else:
        # Return 500 or 404 depending on logic, keeping it simple here
        return {"status": "error", "message": "Failed to remove game"}

@app.post("/rebuild-library")
def rebuild_library():
    response = system.rebuild_library()
    return response

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

# - - - GITHUB RELEASES - - -

@app.get("/version")
def get_version():
    """The version of ISObe that is currently running."""
    return {"version": version.__version__, "repo": updates.get_repo()}

@app.get("/updates")
def get_updates(force: bool = False):
    """Compare the running version against the newest release on GitHub."""
    return updates.check_for_updates(force=force)

@app.get("/releases")
def get_releases(limit: int = 10, force: bool = False):
    """Recent releases from GitHub, newest first."""
    try:
        return {"status": "success", "releases": updates.get_releases(limit=limit, force=force)}
    except Exception as e:
        return {"status": "error", "message": str(e), "releases": []}

# - - - GITHUB RELEASES - - -

# Serve actual web app
@app.get("/{full_path:path}")
def serve_app():
    if os.path.exists(WEB_APP_PATH):
        return FileResponse(WEB_APP_PATH)
    return {"error": "Frontend build not found. Verify that build exists & is routed properly."}

    
if __name__ == "__main__":
    # system checks
    system.CheckDatabases()
    print(f'[SERVER] ISObe v{version.__version__} running on {HOST}:{PORT}')
    uvicorn.run(app, host=HOST, port=PORT)
    pass
