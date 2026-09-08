from colorama import Fore, Style
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel
import uvicorn
import os
import shutil
import uuid
from typing import Optional

# local modules
import system
from system import *
import updates
import updater
import version
import vmc

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


class VMCCreate(BaseModel):
    name: str
    size_mb: int = 8


class VMCAssign(BaseModel):
    name: str
    slot: int = 0


class VMCSettings(BaseModel):
    auto_provision: Optional[bool] = None
    default_size_mb: Optional[int] = None


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

def _uploads_in_flight():
    """Job ids still copying to the drive. Updating would kill the transfer."""
    return [job for job, result in JOB_RESULT.items()
            if isinstance(result, dict) and result.get("status") == "processing"]


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

@app.post("/updates/install")
def install_update(force: bool = False):
    """
    Download and install the newest release, then restart.

    Only ever reached because the user pressed the button: ISObe does not
    update itself in the background, and the update check never triggers this.
    """
    busy = _uploads_in_flight()
    if busy:
        return {
            "status": "error",
            "message": f"{len(busy)} game(s) still transferring to the drive. "
                       "Wait for them to finish, then update.",
        }
    return updater.start_install(force=force)


@app.get("/updates/install/status")
def install_status():
    """Progress of a running install, plus the outcome of the last one."""
    return updater.get_state()


@app.post("/updates/install/dismiss")
def dismiss_install_result():
    """Clear the banner reporting how the last install went."""
    updater.clear_last_result()
    return {"status": "success"}

# - - - GITHUB RELEASES - - -

# - - - VIRTUAL MEMORY CARDS - - -

@app.get("/vmc")
def list_vmcs():
    """Every VMC on the drive, with the games each is bound to."""
    return {
        "status": "success",
        "sizes": list(vmc.VALID_SIZES_MB),
        "vmcs": vmc.list_vmcs(),
    }


@app.post("/vmc")
def create_vmc(payload: VMCCreate):
    """Create and format a new memory card."""
    return vmc.create_vmc(payload.name, payload.size_mb)


@app.delete("/vmc/{name}")
def delete_vmc(name: str):
    """Delete a memory card and unbind it from any game using it."""
    return vmc.delete_vmc(name)



@app.get("/vmc/{name}/saves")
def browse_vmc(name: str):
    """Read the saves off a card. Opens the image read-only."""
    return vmc.browse_vmc(name)


@app.get("/vmc/{name}/export")
def export_vmc(name: str, fmt: str = "raw"):
    """
    Download a card, either as-is or converted to PCSX2's .ps2 format.

    The converted file is built in the uploads folder and deleted once the
    response has been sent; the raw format streams the card itself.
    """
    result = vmc.export_vmc(name, fmt, workdir=system.CONFIG.UPLOADS_PATH)
    if result["status"] != "success":
        return JSONResponse(status_code=400, content=result)

    cleanup = None
    if result["temporary"]:
        cleanup = BackgroundTask(_discard, result["path"])

    return FileResponse(
        result["path"],
        media_type="application/octet-stream",
        filename=result["filename"],
        background=cleanup,
    )


@app.post("/vmc/import")
def import_vmc(file: UploadFile = File(...), name: str = Form(None),
               overwrite: bool = Form(False)):
    """
    Add an existing memory card to the library, converting from PCSX2's format
    if that's what was uploaded.
    """
    if not system.CONFIG.UPLOADS_PATH:
        return {"status": "error", "message": "No storage device selected."}

    os.makedirs(system.CONFIG.UPLOADS_PATH, exist_ok=True)
    temp_path = os.path.join(system.CONFIG.UPLOADS_PATH, f"vmc-import-{uuid.uuid4().hex}")
    try:
        with open(temp_path, 'wb') as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        _discard(temp_path)
        return {"status": "error", "message": f"Upload failed: {e}"}

    # Fall back to the uploaded filename so a dropped card still gets a name.
    label = name or os.path.splitext(os.path.basename(file.filename or ""))[0]
    try:
        return vmc.import_vmc(temp_path, label, overwrite=overwrite)
    finally:
        _discard(temp_path)


def _discard(path):
    """Remove a scratch file, ignoring one that has already gone."""
    try:
        os.remove(path)
    except OSError:
        pass


@app.get("/library/{serial}/vmc")
def get_game_vmc(serial: str):
    """The VMC bound to each of a game's two memory card slots."""
    return {"status": "success", "slots": vmc.get_assignments(serial)}


@app.post("/library/{serial}/vmc")
def assign_game_vmc(serial: str, payload: VMCAssign):
    """Bind a VMC to one of a game's memory card slots."""
    return vmc.assign_vmc(serial, payload.name, payload.slot)


@app.delete("/library/{serial}/vmc/{slot}")
def unassign_game_vmc(serial: str, slot: int):
    """Clear one of a game's memory card slots."""
    return vmc.unassign_vmc(serial, slot)


@app.get("/settings/vmc")
def get_vmc_settings():
    return {
        "status": "success",
        "auto_provision": system.CONFIG.VMC_AUTO_PROVISION,
        "default_size_mb": system.CONFIG.VMC_DEFAULT_SIZE_MB,
        "sizes": list(vmc.VALID_SIZES_MB),
    }


@app.post("/settings/vmc")
def update_vmc_settings(payload: VMCSettings):
    return system.set_vmc_settings(payload.auto_provision, payload.default_size_mb)

# - - - VIRTUAL MEMORY CARDS - - -

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
