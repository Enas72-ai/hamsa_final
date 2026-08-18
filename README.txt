HAMSA — Final Project Folder
==============================

This folder contains ONLY the files you need. Delete any other
index.html / server.py copies elsewhere (Downloads, Desktop, etc.)
to avoid opening the wrong one by mistake.

Files:
  server.py          -> Flask backend (Gemini AI + Knowledge Base)
  index.html          -> Frontend (English UI)
  kb_hamsa.json       -> Knowledge Base (used by server.py)
  requirements.txt    -> Python dependencies
  .env                -> Your Gemini API key goes here

--------------------------------------------------------------
SETUP (run once)
--------------------------------------------------------------
1. Open Terminal in this folder.
2. Create and activate a virtual environment:
     python3 -m venv venv
     source venv/bin/activate
3. Install dependencies:
     pip install -r requirements.txt
4. Open .env and replace the placeholder with your real key:
     GEMINI_API_KEY=your_real_key_here
     GEMINI_MODEL=gemini-2.5-flash

--------------------------------------------------------------
RUN (every time)
--------------------------------------------------------------
1. In Terminal, inside this folder, with (venv) active:
     python server.py
   You should see: Running on http://127.0.0.1:8000
   Leave this Terminal window open.

2. Open index.html directly in your browser (double-click it,
   or drag it into a browser window).
   It already points to http://127.0.0.1:8000 — do not rename
   or move server.py relative to index.html's expectations.

3. Choose a destination or capture a photo, then click
   "Generate Personalized Story".

--------------------------------------------------------------
If something fails
--------------------------------------------------------------
- "Could not connect to the HAMSA backend" -> server.py is not
  running, or it's running on a different port. Check the
  Terminal window.
- Any Python import error -> re-run:
     pip install -r requirements.txt
  while (venv) is active.
