import os
import librosa
import numpy as np
import whisper
from scipy.signal import find_peaks
from moviepy.editor import VideoFileClip
import ffmpeg
from transformers import pipeline

class VideoProcessor:
    def __init__(self, video_path, output_folder, job_id):
        self.video_path = video_path
        self.output_folder = os.path.join(output_folder, job_id)
        self.job_id = job_id
        os.makedirs(self.output_folder, exist_ok=True)
        self.audio_path = os.path.join(self.output_folder, 'audio.wav')

        # Load DistilBERT for humor detection (lightweight, fast)
        print("Loading DistilBERT model...")
        self.humor_classifier = pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
            device=-1  # CPU inference
        )

    def extract_audio(self):
        """Extract audio from video"""
        print("Extracting audio...")
        video = VideoFileClip(self.video_path)
        video.audio.write_audiofile(self.audio_path, verbose=False, logger=None)
        video.close()

    def find_energy_peaks(self):
        """Find high-energy moments using librosa"""
        print("Analyzing audio energy...")
        y, sr = librosa.load(self.audio_path, sr=22050)

        # Calculate RMS energy
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]

        # Find peaks (top 25% energy, at least 10s apart)
        threshold = np.percentile(rms, 75)
        min_distance = int(10 * sr / 512)  # 10 seconds apart

        peaks, properties = find_peaks(rms, height=threshold, distance=min_distance)

        # Convert frame indices to timestamps
        peak_times = librosa.frames_to_time(peaks, sr=sr, hop_length=512)
        peak_energies = rms[peaks]

        return peak_times, peak_energies, y, sr

    def transcribe_video(self):
        """Transcribe video using Whisper"""
        print("Transcribing video... (this may take a few minutes)")
        model = whisper.load_model("tiny")  # Use 'base' for better accuracy
        result = model.transcribe(self.video_path, language="en")
        return result

    def score_humor_keywords(self, text):
        """Keyword-based humor scoring (fast baseline)"""
        if not text:
            return 0

        text_lower = text.lower()
        score = 0

        # Humor keywords
        humor_keywords = ['haha', 'lol', 'funny', 'hilarious', 'laugh', 
                         'omg', 'wow', 'no way', 'seriously', 'amazing',
                         'crazy', 'insane', 'unbelievable', 'ridiculous']

        for keyword in humor_keywords:
            score += text_lower.count(keyword) * 2

        # Exclamations indicate excitement
        score += text.count('!') * 1.5

        # Questions (potential setup)
        score += text.count('?') * 0.5

        # Multiple laughs in sequence
        if 'haha' in text_lower or 'hahaha' in text_lower:
            score += 3

        return score

    def score_humor_bert(self, text):
        """DistilBERT-based semantic humor scoring"""
        if not text or len(text.strip()) < 10:
            return 0

        try:
            # Split into chunks if text is long (BERT has 512 token limit)
            max_length = 500  # characters, roughly ~100 tokens
            chunks = [text[i:i+max_length] for i in range(0, len(text), max_length)]

            scores = []
            for chunk in chunks[:3]:  # Process max 3 chunks to stay fast
                result = self.humor_classifier(chunk, truncation=True)[0]

                # POSITIVE sentiment often correlates with humor/excitement
                if result['label'] == 'POSITIVE':
                    scores.append(result['score'] * 10)
                else:
                    # Negative can also be funny (sarcasm, irony)
                    scores.append(result['score'] * 3)

            return np.mean(scores) if scores else 0

        except Exception as e:
            print(f"BERT scoring error: {e}")
            return 0

    def score_humor(self, text):
        """Hybrid humor scoring: keywords + DistilBERT"""
        keyword_score = self.score_humor_keywords(text)
        bert_score = self.score_humor_bert(text)

        # Weighted combination: 40% keywords (fast, explicit), 60% BERT (semantic)
        combined_score = 0.4 * keyword_score + 0.6 * bert_score

        return combined_score

    def extract_clip_transcript(self, start_time, end_time, transcription):
        """Get transcript text for a specific time window"""
        clip_text = ""
        for segment in transcription['segments']:
            seg_start = segment['start']
            seg_end = segment['end']

            # Check if segment overlaps with clip window
            if not (seg_end < start_time or seg_start > end_time):
                clip_text += segment['text'] + " "

        return clip_text.strip()

    def create_candidates(self, peak_times, peak_energies, transcription):
        """Create scored candidate clips"""
        print("Scoring candidate clips with DistilBERT...")
        candidates = []
        video = VideoFileClip(self.video_path)
        video_duration = video.duration
        video.close()

        for i, peak_time in enumerate(peak_times):
            # Define clip window (±30 seconds around peak)
            clip_start = max(0, peak_time - 30)
            clip_end = min(video_duration, peak_time + 30)

            # Get transcript for this window
            clip_transcript = self.extract_clip_transcript(clip_start, clip_end, transcription)

            # Calculate scores
            energy_score = peak_energies[i]
            humor_score = self.score_humor(clip_transcript)

            # Normalize energy (0-10 scale)
            normalized_energy = (energy_score / np.max(peak_energies)) * 10

            # Combined score: 40% energy, 60% humor (humor weighted higher for "funny moments")
            total_score = 0.4 * normalized_energy + 0.6 * humor_score

            candidates.append({
                'start': float(clip_start),
                'end': float(clip_end),
                'transcript': clip_transcript,
                'energy_score': float(normalized_energy),
                'humor_score': float(humor_score),
                'total_score': float(total_score)
            })

            print(f"  Candidate {i+1}: Energy={normalized_energy:.1f}, Humor={humor_score:.1f}, Total={total_score:.1f}")

        return candidates

    def cut_clips(self, top_clips):
        """Extract top 3 clips from video"""
        print("Cutting video clips...")
        output_clips = []

        for i, clip in enumerate(top_clips, 1):
            output_path = os.path.join(self.output_folder, f'clip_{i}.mp4')

            # Use ffmpeg to cut clip (fast, no re-encoding)
            try:
                (
                    ffmpeg
                    .input(self.video_path, ss=clip['start'], t=clip['end'] - clip['start'])
                    .output(output_path, codec='copy', loglevel='quiet')
                    .overwrite_output()
                    .run()
                )

                # Format output
                output_clips.append({
                    'clip_number': i,
                    'start_time': self.format_time(clip['start']),
                    'end_time': self.format_time(clip['end']),
                    'start_seconds': clip['start'],
                    'end_seconds': clip['end'],
                    'explanation': self.generate_explanation(clip),
                    'transcript': clip['transcript'][:200] + '...' if len(clip['transcript']) > 200 else clip['transcript'],
                    'energy_raw': clip['energy_score'],
                    'humor_raw': clip['humor_score'],
                    'clip_path': f'/clip/{self.job_id}/{i}'
                })

            except Exception as e:
                print(f"Error cutting clip {i}: {e}")

        return output_clips

    def format_time(self, seconds):
        """Convert seconds to MM:SS format"""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}:{secs:02d}"

    def generate_explanation(self, clip):
        """Generate human-readable explanation"""
        reasons = []

        # Energy analysis
        if clip['energy_score'] > 8:
            reasons.append("very high audio energy (laughter/excitement)")
        elif clip['energy_score'] > 6:
            reasons.append("high audio energy")

        # Humor analysis (DistilBERT + keywords)
        if clip['humor_score'] > 8:
            reasons.append("strong humor signals detected by AI")
        elif clip['humor_score'] > 5:
            reasons.append("moderate humor indicators")
        elif clip['humor_score'] > 2:
            reasons.append("subtle humor patterns")

        # Transcript quality
        if len(clip['transcript']) > 50:
            reasons.append("engaging dialogue")

        if not reasons:
            reasons.append("notable moment")

        explanation = (
            f"Selected for {', '.join(reasons)}. "
            f"Scores: Energy {clip['energy_score']:.1f}/10, "
            f"Humor {clip['humor_score']:.1f}/10 (AI-enhanced detection)"
        )
        return explanation

    def process(self):
        """Main processing pipeline"""
        # Step 1: Extract audio
        self.extract_audio()

        # Step 2: Find energy peaks
        peak_times, peak_energies, audio_data, sr = self.find_energy_peaks()
        print(f"Found {len(peak_times)} high-energy moments")

        if len(peak_times) == 0:
            print("No high-energy moments found, lowering threshold...")
            # Retry with lower threshold
            y, sr = librosa.load(self.audio_path, sr=22050)
            rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
            threshold = np.percentile(rms, 60)  # Lower threshold
            min_distance = int(10 * sr / 512)
            peaks, _ = find_peaks(rms, height=threshold, distance=min_distance)
            peak_times = librosa.frames_to_time(peaks, sr=sr, hop_length=512)
            peak_energies = rms[peaks]
            print(f"Found {len(peak_times)} moments with lower threshold")

        # Step 3: Transcribe
        transcription = self.transcribe_video()

        # Step 4: Create and score candidates
        candidates = self.create_candidates(peak_times, peak_energies, transcription)

        # Step 5: Select top 3 non-overlapping clips
        top_clips = self.select_top_clips(candidates, n=3)

        # Step 6: Cut video clips
        output_clips = self.cut_clips(top_clips)

        print(f"\nProcessing complete! Generated {len(output_clips)} clips")
        for clip in output_clips:
            print(f"  Clip {clip['clip_number']}: {clip['start_time']}-{clip['end_time']} "
                  f"(E:{clip['energy_raw']:.1f}, H:{clip['humor_raw']:.1f})")

        return output_clips

    def select_top_clips(self, candidates, n=3):
        """Select top N non-overlapping clips"""
        if len(candidates) == 0:
            return []

        # Sort by total score
        sorted_candidates = sorted(candidates, key=lambda x: x['total_score'], reverse=True)

        selected = []
        for candidate in sorted_candidates:
            # Check if overlaps with already selected clips
            overlaps = False
            for selected_clip in selected:
                # Check for overlap
                if not (candidate['end'] < selected_clip['start'] or 
                       candidate['start'] > selected_clip['end']):
                    overlaps = True
                    break

            if not overlaps:
                selected.append(candidate)

            if len(selected) >= n:
                break

        return selected
