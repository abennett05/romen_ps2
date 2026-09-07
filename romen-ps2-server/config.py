class Config:
    LIB_PATH = ""
    UPLOADS_PATH = ""
    FILE_STRUCTURE = ""
    COVERS_URL = ""
    DISCS_URL = ""
    CFG_URL = ""
    GITHUB_REPO = ""

    def __init__(self, json_data : list) -> None:
        self.update_entries(json_data)
    
    def update_entries(self, json_data : list) -> None:
        self.LIB_PATH = json_data["paths"]["storage"]
        self.UPLOADS_PATH = json_data["paths"]["uploads"]
        self.FILE_STRUCTURE = json_data["structure"]
        self.COVERS_URL = json_data["paths"]["covers_url"]
        self.DISCS_URL = json_data["paths"]["discs_url"]
        self.CFG_URL = json_data["paths"]["cfg_url"]
        # Optional: settings.json written by an older version won't have this,
        # so fall back to the repo baked into version.py.
        self.GITHUB_REPO = json_data.get("updates", {}).get("github_repo", "")
