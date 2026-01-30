from video_processor import VideoProcessor
import os

# ⚙️ EDIT THIS PATH TO YOUR LOCAL VIDEO FILE
VIDEO_PATH = "0118.mp4"  # Change this!

def main():
    if not os.path.exists(VIDEO_PATH):
        print(f"❌ Video file not found: {VIDEO_PATH}")
        print("📝 Edit VIDEO_PATH in this script to point to your video file")
        return
    
    print(f"🎬 Processing: {VIDEO_PATH}")
    print(f"📁 Size: {os.path.getsize(VIDEO_PATH) / (1024*1024):.2f} MB\n")
    
    # Run processor
    processor = VideoProcessor(VIDEO_PATH, "test_outputs", "test_001")
    clips = processor.process()
    
    # Show results
    print(f"\n✅ Done! Generated {len(clips)} clips")
    for clip in clips:
        print(f"  Clip {clip['clip_number']}: {clip['start_time']}-{clip['end_time']} "
              f"(E:{clip['energy_raw']:.1f}, H:{clip['humor_raw']:.1f})")

if __name__ == "__main__":
    main()
