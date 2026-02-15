import os
import librosa
import numpy as np
import torch
from moviepy.editor import VideoFileClip
import ffmpeg
from transformers import pipeline

seconds_before_laugh_detected = 20 # edit this according to how much context desired
desired_clip_duration = 40 # edit this for clip duration

class VideoProcessor:
    def __init__(self, video_path, output_folder, job_id, progress_callback=None):
        self.progress_callback = progress_callback
        self.video_path = video_path
        self.output_folder = os.path.join(output_folder, job_id)
        self.job_id = job_id
        os.makedirs(self.output_folder, exist_ok=True)
        self.audio_path = os.path.join(self.output_folder, 'audio.wav')

        # 1. LOAD AUDIO CLASSIFIER
        print("Loading Audio Classifier (AST)...")
        
        # Auto-detect GPU
        device_id = 0 if torch.cuda.is_available() else -1
        device_name = torch.cuda.get_device_name(0) if device_id == 0 else "CPU"
        print(f"   Using device: {device_name}")

        self.audio_classifier = pipeline(
            "audio-classification", 
            model="mit/ast-finetuned-audioset-10-10-0.4593",
            device=device_id 
        )

    def extract_audio(self):
        """Extract audio from video file to WAV if not exists"""
        if not os.path.exists(self.audio_path):
            print("Extracting audio from video...")
            # Signal progress: Extraction started (5%)
            if self.progress_callback: self.progress_callback(5)
            
            try:
                # Use moviepy for reliable extraction
                video = VideoFileClip(self.video_path)
                video.audio.write_audiofile(self.audio_path, verbose=False, logger=None)
                video.close()
            except Exception as e:
                print(f"❌ Error extracting audio with MoviePy: {e}")
                print("Attempting fallback extraction with ffmpeg...")
                try:
                    (
                        ffmpeg
                        .input(self.video_path)
                        .output(self.audio_path, ac=1, ar=16000)
                        .run(overwrite_output=True, quiet=True)
                    )
                except Exception as ffmpeg_err:
                    print(f"❌ FFmpeg extraction also failed: {ffmpeg_err}")
        else:
            print("Audio already extracted, skipping...")

    def find_candidates(self):
        print("Loading audio into memory...")
        y, sr = librosa.load(self.audio_path, sr=16000, mono=True)
        duration = librosa.get_duration(y=y, sr=sr)
        
        candidates = []
        
        # AGGRESSIVE SCANNING SETTINGS
        window_size = 5   # Smaller window to isolate laughter from speech
        step_size = 2     # Dense overlap
        
        timestamps = list(range(0, int(duration) - window_size, step_size))
        total_segments = len(timestamps)
        print(f"Scanning {total_segments} segments (Aggressive Mode)...")
        print("-" * 60)
        
        # Track last logged percentage to avoid spam
        last_logged_pct = -1
        
        for i, start in enumerate(timestamps):
            
            # --- PROGRESS REPORTING ---
            if self.progress_callback:
                # Map scanning loop to 10% -> 90% of total progress
                percent = 10 + int((i / total_segments) * 80)
                
                # Only log every 5% to reduce output
                if percent >= last_logged_pct + 5:
                    print(f"Scanning progress: {percent}% ({i}/{total_segments} segments)")
                    last_logged_pct = percent
                    
                self.progress_callback(percent)
            # --------------------------

            end = start + window_size
            start_sample = int(start * sr)
            end_sample = int(end * sr)
            if end_sample > len(y): break
                
            chunk = y[start_sample:end_sample]
            
            # Energy Check (Keep it low)
            if np.sqrt(np.mean(chunk**2)) < 0.002: continue 

            # Normalize
            max_val = np.max(np.abs(chunk))
            if max_val > 0: chunk = chunk / max_val
            
            chunk = np.ascontiguousarray(chunk, dtype=np.float32)

            try:
                # Return ALL scores (top_k=None) to check sum
                results = self.audio_classifier({"array": chunk, "sampling_rate": 16000}, top_k=10)
                
                score = 0
                # Expanded List of funny sounds
                funny_labels = [
                    'Laughter', 'Giggle', 'Snicker', 'Chuckling', 'Belly laugh', 
                    'Chortle', 'Baby laughter'
                ]
                
                for r in results:
                    if any(label in r['label'] for label in funny_labels):
                        score += r['score']
                
                # LOWER THRESHOLD: 0.001 (0.1%)
                if score > 0.001:
                    # Store candidate (removed verbose logging to prevent systemd journal overflow)
                    candidates.append({
                        'time': start + (window_size/2), 
                        'laughter_score': score,
                        'energy': max_val
                    })
                    
            except Exception as e:
                continue

        print(f"Scanning complete! Found {len(candidates)} candidate moments")
        return candidates

    def process(self):
        """Main execution flow"""
        print(f"Starting video processing for job {self.job_id}")
        print(f"Video path: {self.video_path}")
        
        self.extract_audio()
        
        candidates = self.find_candidates()
        
        if not candidates:
            print("\n❌ No laughter found. (Try checking if audio extracted correctly)")
            return []

        # Sort by score first
        candidates.sort(key=lambda x: x['laughter_score'], reverse=True)
        
        # LOGIC: Filter out duplicates (Non-Maximum Suppression)
        unique_clips = []
        for cand in candidates:
            # Check if this candidate overlaps with any we've already selected
            is_overlap = False
            for selected in unique_clips:
                # If time difference is less than 30 seconds, it's the same moment
                if abs(cand['time'] - selected['time']) < 30:
                    is_overlap = True
                    break
            
            if not is_overlap:
                unique_clips.append(cand)
            
            if len(unique_clips) >= 3: # Stop once we have 3 unique moments
                break
        
        top_clips = unique_clips # Use this list for cutting
        
        print("\n" + "="*50)
        print("🎉 TOP 3 LAUGHTER MOMENTS")
        print("="*50)
        for i, c in enumerate(top_clips):
            m = int(c['time'] // 60)
            s = int(c['time'] % 60)
            print(f"{i+1}. {m}:{s:02d} (Score: {c['laughter_score']:.3f})")
        print("="*50 + "\n")

        print(f"Cutting {len(top_clips)} clips...")
        
        # Signal Cutting Started (90%)
        if self.progress_callback: self.progress_callback(90)

        output_clips = []
        
        # Get duration safely
        try:
            print("Getting video duration...")
            video_clip = VideoFileClip(self.video_path)
            full_duration = video_clip.duration
            video_clip.close()
            print(f"Video duration: {full_duration}s")
        except Exception as e:
            print(f"⚠️ Could not get video duration: {e}")
            import traceback
            print(traceback.format_exc())
            full_duration = 99999
        
        for i, clip in enumerate(top_clips):
            # Window: +/- 20s
            start = max(0, clip['time'] - seconds_before_laugh_detected)
            end = min(start + desired_clip_duration, full_duration)
            
            out_path = os.path.join(self.output_folder, f"clip_{i+1}.mp4")
            
            print(f"\nAttempting to cut clip {i+1}:")
            print(f"  Start: {start:.2f}s, End: {end:.2f}s, Duration: {end-start:.2f}s")
            print(f"  Output: {out_path}")
            
            try:
                (
                    ffmpeg
                    .input(self.video_path, ss=start, t=end-start)
                    .output(out_path, codec='copy', loglevel='error')
                    .overwrite_output()
                    .run(capture_stdout=True, capture_stderr=True)
                )
                
                # Verify the file was created
                if os.path.exists(out_path):
                    file_size = os.path.getsize(out_path)
                    print(f"✅ Saved: {out_path} ({file_size} bytes)")
                    # Store timing info with the clip
                    output_clips.append({
                        'path': out_path,
                        'start_time': start,
                        'end_time': end
                    })
                else:
                    print(f"❌ File was not created: {out_path}")
                    
            except ffmpeg.Error as e:
                print(f"❌ FFmpeg error cutting clip {i+1}:")
                print(f"   stdout: {e.stdout.decode() if e.stdout else 'None'}")
                print(f"   stderr: {e.stderr.decode() if e.stderr else 'None'}")
            except Exception as e:
                import traceback
                print(f"❌ Unexpected error cutting clip {i+1}: {e}")
                print(traceback.format_exc())

        print(f"\n{'='*50}")
        print(f"Job completed! Generated {len(output_clips)} out of {len(top_clips)} clips")
        print(f"{'='*50}\n")
        
        return output_clips