import pycdlib
import io
import re

def get_serial(iso_path) -> str:
    iso = pycdlib.PyCdlib()
    try:
        # Open the ISO file
        iso.open(iso_path)
        # PS2 games always have a SYSTEM.CNF file at the root
        # We read it into a BytesIO object so we can decode it
        bio = io.BytesIO()
        iso.get_file_from_iso_fp(bio, iso_path='/SYSTEM.CNF;1')
        content = bio.getvalue().decode('utf-8', errors='ignore')
        # Look for the BOOT2 line (e.g., "BOOT2 = cdrom0:\SLUS_200.02;1")
        # We want to capture the pattern XXXX_000.00
        match = re.search(r'cdrom0:\s?\\(.*?);', content, re.IGNORECASE)
        if match:
            # Returns the raw serial, e.g., "SLUS_200.02"
            return match.group(1)
        else:
            return None
    except Exception as e:
        return None
    finally:
        # Always close the ISO to free up resources
        iso.close()
        