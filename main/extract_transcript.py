import whisper
import sys
import os

def extract_transcript(video_path, model_size="base"):
    """
    Extracts transcript from a video file using OpenAI Whisper.
    """
    if not os.path.exists(video_path):
        print(f"❌ Error: File '{video_path}' not found.")
        return

    print(f"📥 Loading Whisper model ('{model_size}')...")
    model = whisper.load_model(model_size)

    print(f"🎧 Transcribing '{video_path}'... (This may take a moment)")
    # language="en" forces English, remove if you need multi-language support
    result = model.transcribe(video_path, language="en") 

    # Generate filenames
    base_name = os.path.splitext(video_path)[0]
    txt_path = f"{base_name}_transcript.txt"
    time_path = f"{base_name}_timestamps.txt"

    # 1. Save Pure Text
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(result["text"].strip())

    # 2. Save With Timestamps (Great for finding "haha" moments)
    with open(time_path, "w", encoding="utf-8") as f:
        for segment in result["segments"]:
            start = int(segment['start'])
            min_sec = f"{start // 60}:{start % 60:02d}"
            f.write(f"[{min_sec}] {segment['text']}\n")

    print(f"\n✅ Done!")
    print(f"   📄 Text only:      {txt_path}")
    print(f"   ⏱️ With timings:   {time_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_transcript.py <path_to_video>")
    else:
        # You can change "base" to "tiny" for speed or "small" for better accuracy
        extract_transcript(sys.argv[1], model_size="tiny")
