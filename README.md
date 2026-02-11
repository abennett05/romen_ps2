<img src="https://github.com/abennett05/romen_ps2/blob/main/romen-ps2-front/public/img/romen_logo.png?raw=true" alt="Romen Logo" width="192">

# Romen-PS2 🎮

**A robust web server and library manager for your PlayStation 2 ISO collection.**

> **Status:** 🚧 Public Beta (v0.1.1)

**Romen** is a Python-based web application designed to streamline the process of managing PS2 game backups. It automates the tedious tasks required for Open PS2 Loader (OPL) compatibility and **allows any device on your local network to upload games**.

## ✨ Features

* **ISO Auto-Identification:** automatically reads the game serial number (e.g., `SLUS_200.02`) from inside the ISO file.
* **OPL Compliant Renaming:** Renames files to the standard format required by Open PS2 Loader (e.g., `SLUS_200.02.Game Name.iso`).
* **Web Interface:** Manage your library via a modern React-based frontend.
* **Database Tracking:** Maintains a local database of your owned games.
* **Cross-Platform:** Runs seamlessly on Windows, macOS, and Linux.
* **Game Art:** Fetches appropiate artwork for your games to view in the **Romen** app & OPL.

---

## 📋 Requirements

* 💿 Additional Storage Device formatted in **exFAT**
   * Spare USB Drive, SATA HDD, NVME M.2 SSD, whatever you have likely works!
* 🐍 [Python (3.1x)](https://www.python.org/) installed on the system running Romen.

---

## 📥 How to Download & Run (For Users)

If you just want to use the tool to manage your games, you do **not** need to clone this repository.

1.  **Go to the [Releases Page](../../releases)**.
2.  Download the latest `.zip` file (e.g., `romen-ps2-v0.1.1.zip`).
3.  Unzip the folder.
4.  **Run the script:**
    * **Windows:** Double-click `run.bat`.
    * **Mac/Linux:** Open terminal in the folder and run `./run.sh`.
5.  **View in your browser & start uploading games!**.

---

## 📄 License
This project is open source and available under the [MIT License](LICENSE).
