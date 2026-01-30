import os
import librosa
import numpy as np
import torch
from moviepy.editor import VideoFileClip
import ffmpeg
from transformers import pipeline
from tqdm import tqdm  # Progress bar

class VideoProcessor:
    def __init__(self, video_path, output_folder, job_id):
        self.video_path = video_path
        self.output_folder = os.path.join(output_folder, job_id)
        self.job_id = job_id
        os.makedirs(self.output_folder, exist_ok=True)
        self.audio_path = os.path.join(self.output_folder, 'audio.wav')

        # 1. LOAD AUDIO CLASSIFIER
        # Using a slightly smaller batch size for CPU safety, increase to 4 or 8 if you have RAM
        print("Loading Audio Classifier (AST)...")
        self.audio_classifier = pipeline(
            "audio-classification", 
            model="mit/ast-finetuned-audioset-10-10-0.4593",
            device=-1  # CPU
        )

    def extract_audio(self):
        if not os.path.exists(self.audio_path):
            print("Extracting audio from video...")
            video = VideoFileClip(self.video_path)
            video.audio.write_audiofile(self.audio_path, verbose=False, logger=None)
            video.close()
        else:
            print("Audio already extracted, skipping...")

    def find_candidates(self):
            print("Loading audio into memory...")
            y, sr = librosa.load(self.audio_path, sr=16000)
            duration = librosa.get_duration(y=y, sr=sr)
            
            candidates = []
            timestamps = list(range(0, int(duration) - 10, 5)) # Step=5s, Window=10s
            
            print(f"Scanning {len(timestamps)} segments for laughter...")
            print("-" * 50)
            print(f"{'TIME':<10} | {'SCORE':<10} | {'STATUS'}")
            print("-" * 50)
            
            for start in tqdm(timestamps, desc="Scanning", unit="seg", leave=False):
                end = start + 10
                
                # Extract chunk
                start_sample = start * sr
                end_sample = end * sr
                chunk = y[start_sample:end_sample]
                
                # Energy check
                rms = np.sqrt(np.mean(chunk**2))
                if rms < 0.01: continue

                try:
                    # Inference
                    results = self.audio_classifier(
                        {"array": chunk, "sampling_rate": 16000}, 
                        top_k=5
                    )
                    
                    # Calculate Score
                    score = 0
                    for r in results:
                        if r['label'] in ['Laughter', 'Giggle', 'Chuckling', 'Snicker']:
                            score += r['score']
                    
                    # PRINT DETECTION
                    if score > 0.15: # Threshold to show in console
                        min_sec = f"{start // 60}:{start % 60:02d}"
                        bar = "█" * int(score * 10)
                        tqdm.write(f"{min_sec:<10} | {score:.3f}      | {bar} Laughter detected")
                        
                        candidates.append({
                            'time': start + 5, # Center timestamp
                            'laughter_score': score,
                            'energy': rms
                        })
                        
                except Exception as e:
                    continue

            return candidates

    def process(self):
            self.extract_audio()
            candidates = self.find_candidates()
            
            if not candidates:
                print("No laughter found.")
                return []

            # Sort and take top 3
            candidates.sort(key=lambda x: x['laughter_score'], reverse=True)
            top_clips = candidates[:3]
            
            print("\n" + "="*50)
            print("TOP 3 LAUGHTER MOMENTS FOUND")
            print("="*50)
            for i, c in enumerate(top_clips):
                m = int(c['time'] // 60)
                s = int(c['time'] % 60)
                print(f"{i+1}. {m}:{s:02d} (Score: {c['laughter_score']:.3f})")
            print("="*50 + "\n")

            print(f"Cutting {len(top_clips)} clips...")
            
            output_clips = []
            for i, clip in enumerate(top_clips):
                start = max(0, clip['time'] - 20)
                end = min(start + 40, VideoFileClip(self.video_path).duration)
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
                except Exception as e:
                    print(f"Error cutting clip {i+1}: {e}")
                
            return output_clips