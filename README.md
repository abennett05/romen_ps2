<img src="https://github.com/abennett05/isobe/blob/main/romen-ps2-front/public/img/romen_logo.png?raw=true" alt="ISObe Logo" width="192">

# ISObe-PS2 🎮

**A robust web server and library manager for your PlayStation 2 ISO collection.**

<img src="https://i.imgur.com/kkH9c6K.jpeg" alt="ISObe Preview Image" width="1280" height="720">

> **Status:** 🚧 Public Beta (v0.3.0)

**ISObe** is a Python-based web application designed to streamline the process of managing PS2 game backups. It automates the tedious tasks required for Open PS2 Loader (OPL) compatibility and **allows any device on your local network to upload games**.

## ✨ Features

* **ISO Auto-Identification:** automatically reads the game serial number (e.g., `SLUS_200.02`) from inside the ISO file.
* **OPL Compliant Renaming:** Renames files to the standard format required by Open PS2 Loader (e.g., `SLUS_200.02.Game Name.iso`).
* **Web Interface:** Manage your library via a modern React-based frontend.
* **Database Tracking:** Maintains a local database of your owned games.
* **Cross-Platform:** Runs seamlessly on Windows, macOS, and Linux.
* **Game Art:** Fetches appropiate artwork for your games to view in the **ISObe** app & OPL.
* **Game CFG:** Collects information about the game such as Developer, Release Date, Genre, & Description to display in OPL.
* **Virtual Memory Cards:** Create formatted VMCs (8-64MB) from your browser and assign them to games, so every title can have its own memory card without touching the console's menus. Deleting a game keeps its card, so saves are never lost.
* **One-Click Updates:** When a new release is out, ISObe can download, verify and install it itself, then restart — no unzipping. Updates only ever run when you press the button; ISObe never updates itself in the background, keeps a backup, and rolls back if anything goes wrong. Your settings, library and memory cards are untouched.

---

## 📋 Requirements

* 💿 Additional Storage Device formatted in **exFAT**
   * Spare USB Drive, SATA HDD, NVME M.2 SSD, whatever you have likely works!
* 🐍 [Python (3.1x)](https://www.python.org/) installed on the system running ISObe.

---

## 📥 How to Download & Run (For Users)

If you just want to use the tool to manage your games, you do **not** need to clone this repository.

1.  **Go to the [Releases Page](../../releases)**.
2.  Download the latest `.zip` file (e.g., `isobe-ps2-v0.3.1.zip`).
3.  Unzip the folder.
4.  **Run the script:**
    * **Windows:** Double-click `run.bat`.
    * **Mac/Linux:** Open terminal in the folder and run `./run.sh`.
5.  **View in your browser & start uploading games!**.
++ Once setup, ISObe will automatically search for updates!

---

## 🚀 Releasing (For Maintainers)

Releases are built and published automatically by
[`.github/workflows/release.yml`](.github/workflows/release.yml). Pushing a
version tag is the whole process:

```bash
git tag v0.4.0
git push origin v0.4.0
```

The workflow builds the React frontend, packages it with the Python server and
launch scripts, stamps the version into `version.py`, and attaches
`isobe-ps2-v0.4.0.zip` to a new GitHub Release. Tags containing `-beta`,
`-alpha` or `-rc` are published as pre-releases.

To test the packaging without publishing, run the workflow manually from the
**Actions** tab — it produces the same zip as a downloadable build artifact.

> Tags must match the version scheme in `romen-ps2-server/version.py` (`v0.4.0`
> ↔ `0.4.0`), since the in-app update check compares the running version against
> the latest release tag.

---

## 📄 License
This project is open source and available under the [MIT License](LICENSE).
