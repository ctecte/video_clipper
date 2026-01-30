import os
import uuid
import threading
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
import yt_dlp

# Import your existing processor
from video_processor import VideoProcessor

app = Flask(__name__)
CORS(app) # Enable React to talk to Flask

# Config
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# In-memory storage for job status (Use Redis/DB in production)
jobs = {}

# In app.py

def run_processor_background(job_id, video_path):
    """
    Runs the heavy AI processing in a background thread.
    Updates the global 'jobs' dictionary with progress.
    """
    try:
        jobs[job_id]['status'] = 'processing'
        jobs[job_id]['progress'] = 0  # Initialize progress

        # DEFINE THE CALLBACK
        # This function gets called by VideoProcessor whenever percentage changes
        def update_progress(p):
            jobs[job_id]['progress'] = p
            print(f"Job {job_id} progress: {p}%") # Optional logging

        # PASS THE CALLBACK
        processor = VideoProcessor(
            video_path, 
            OUTPUT_FOLDER, 
            job_id, 
            progress_callback=update_progress # <--- Connects the dots
        )
        
        clips = processor.process()
        
        # Process results for frontend
        results = []
        for i, clip_path in enumerate(clips):
            filename = os.path.basename(clip_path)
            results.append({
                'id': i + 1,
                'filename': filename,
                'url': f"/download/{job_id}/{filename}"
            })
            
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['progress'] = 100
        jobs[job_id]['results'] = results
        
    except Exception as e:
        print(f"Job {job_id} failed: {e}")
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['error'] = str(e)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    # security reasons. Can allow .mov .avi also but since project specified export in mp4 then mp4 it is
    if not file.filename.endswith('.mp4'):
        return jsonify({"error": "Only mp4 supported"}), 400
    
    job_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    save_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{filename}")
    file.save(save_path)
    
    # Initialize Job
    jobs[job_id] = {
        "status": "queued", 
        "video_path": save_path,
        "type": "upload"
    }
    
    # Start Processing Immediately
    thread = threading.Thread(target=run_processor_background, args=(job_id, save_path))
    thread.start()
    
    return jsonify({"job_id": job_id, "status": "queued"})

@app.route('/youtube', methods=['POST'])
def process_youtube():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    job_id = str(uuid.uuid4())

    # 1. Download with yt-dlp
    def download_and_process():
        # --- NEW: Progress Hook function ---
        def progress_hook(d):
            if d['status'] == 'downloading':
                try:
                    # yt-dlp provides downloaded_bytes and total_bytes
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    
                    if total > 0:
                        percent = int((downloaded / total) * 100)
                        jobs[job_id]['progress'] = percent
                        print(f"[HOOK] Job {job_id}: {percent}%")  # Debug log
                    
                except Exception as e:
                    print(f"Progress hook error: {e}")
                    pass
            elif d['status'] == 'finished':
                jobs[job_id]['progress'] = 100
                print(f"[HOOK] Download finished for {job_id}")

        try:
            jobs[job_id]['status'] = 'downloading'
            jobs[job_id]['progress'] = 0
            
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': os.path.join(UPLOAD_FOLDER, f"{job_id}_%(title)s.%(ext)s"),
                'progress_hooks': [progress_hook],  # <--- Add the hook here
                'quiet': True,
                'no_warnings': True
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_path = ydl.prepare_filename(info)
            
            # 2. Hand off to Processor
            run_processor_background(job_id, video_path)
            
        except Exception as e:
            print(f"Download Error: {e}")
            jobs[job_id]['status'] = 'failed'
            jobs[job_id]['error'] = str(e)

    jobs[job_id] = {"status": "initializing", "type": "youtube", "progress": 0}
    
    thread = threading.Thread(target=download_and_process)
    thread.start()
    
    return jsonify({"job_id": job_id, "status": "initializing"})

@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

@app.route('/download/<job_id>/<filename>')
def serve_output(job_id, filename):
    # Serve the clips so the frontend can play them
    return send_from_directory(os.path.join(OUTPUT_FOLDER, job_id), filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
