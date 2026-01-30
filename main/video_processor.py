import os
import librosa
import numpy as np
import torch
from moviepy.editor import VideoFileClip
import ffmpeg
from transformers import pipeline
from tqdm import tqdm

class VideoProcessor:
    def __init__(self, video_path, output_folder, job_id):
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
        print(f"Scanning {len(timestamps)} segments (Aggressive Mode)...")
        print("-" * 60)
        
        for start in tqdm(timestamps, desc="Scanning", unit="seg"):
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
                
                # LOWER THRESHOLD: 0.02 (2%)
                # If 2% of the audio signature is laughter, we want it.
                if score > 0.02:
                    min_sec = f"{start // 60}:{start % 60:02d}"
                    bar = "█" * int(score * 100) # Scale bar for visibility
                    tqdm.write(f"{min_sec:<10} | {score:.3f}      | {bar}")
                    
                    candidates.append({
                        'time': start + (window_size/2), 
                        'laughter_score': score,
                        'energy': max_val
                    })
                    
            except Exception as e:
                continue

        return candidates

    def process(self):
        """Main execution flow"""
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
        output_clips = []
        
        # Get duration safely
        try:
            full_duration = VideoFileClip(self.video_path).duration
        except:
            full_duration = 99999
        
        for i, clip in enumerate(top_clips):
            # Window: +/- 20s
            start = max(0, clip['time'] - 20)
            end = min(start + 60, full_duration)
            
            out_path = os.path.join(self.output_folder, f"clip_{i+1}.mp4")
            
            try:
                (
                    ffmpeg
                    .input(self.video_path, ss=start, t=end-start)
                    .output(out_path, codec='copy', loglevel='quiet')
                    .overwrite_output()
                    .run()
                )
                output_clips.append(out_path)
                print(f"✅ Saved: {out_path}")
            except Exception as e:
                print(f"❌ Error cutting clip {i+1}: {e}")
                print(f"   Command likely failed. Ensure 'ffmpeg' is in PATH.")
            
        return output_clips
