class Config:
    LIB_PATH = ""
    UPLOADS_PATH = ""
    FILE_STRUCTURE = ""
    COVERS_URL = ""

    def __init__(self, json_data : list) -> None:
        self.update_entries(json_data)
    
    def update_entries(self, json_data : list) -> None:
        self.LIB_PATH = json_data["paths"]["storage"]
        self.UPLOADS_PATH = json_data["paths"]["uploads"]
        self.FILE_STRUCTURE = json_data["structure"]
        self.COVERS_URL = json_data["paths"]["covers_url"]
