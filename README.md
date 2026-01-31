# Development Process and decisions
To begin, I first attempted to use a few features to decide "best", which I define as humor and funny moments

### Audio Peaks
Starting with audio peaks, I tried to score certain context based on high peaks and energy.

that failed as it just clipped moments where people talked loudly or got excited


### Audio Transcription
Next, I tried audio transcription for better context. I experimented with BERT (Bidirectional Encoded Regression Transformer) which could in theory recognize humor and sarcasm etc from subtitles. 

the output was not really interesting among multiple videos I tested with. I explicitly looked for keywords like "lol", "no way", "omg" but it did not improve performance by noticable means. 

### Overcomplicating?

So I realised that I was overcomplicating the filtering, and decided to try a simple foolproof plan of AST

### Winning algorithm: AST
AST aka Audio Spectrogram Transformers can classify portions of audio. For example: Laughter, Giggle, Snicker. Those were the highlights to me, and I decided to test using these. Of note is that AST does require heavy parallelisation to work well, so a GPU is needed. This is important for the choice of aws ec2 instance.

By selecting clips that have laughter in their top 5 classification tags, I reliably found clips where there is a funny moment. Which to me are why I watch clips. 

Sorting them by laughter score gives me the top 3 clips, which is what I then serve back to the requester.

The clipper works best for podcast/mukbang/vlog style videos where there are many funny moments that might be scattered throughout a 1 hour video. The output is deterministic which is good for testing and fine-tuning certain metrics, or comparing performance against different publically available AST datasets. 

I sampled with various daily ketchup videos and found that most of them were pretty interesting, or at least I would see them laughing. Good place to start hunting for clips. 

"Mr Pritam please take one for the team!".

### Discussing the clip rankings, tradeoffs and future improvements

As mentioned, the AST algorithm identities clips with prominent laughter. By ranking those that have higher correlation to laughing, I can get the clips where people are laughing heavily. These make good candidates for the "best" clips by my editorial definition.

The tradeoffs are that it is a really simple formula, and there will be a lot of "bruh moments", or deadpan gold comedy that is missed out. Imagine a scene where a crow flying over . .  .  . being missed out. 

For further improvements, I would consider transcribing with BERT still. Although it would require a lot of tuning, I believe that editing is best done when you have a wide pool of clips to choose from. Having BERT present and mixing in 1 clip of humor rather than heavy laughter might better match a range of user expectations.


# Building the rest
I tested the main logic in video_procsssor.py, and once it was working, it was a matter of creating frontend and endpoints to hit for downloading and displaying of the produced clips. 

# AWS deployment
Machine of choice is the g4dn.xlarge with a T4 Nvidia GPU and 16gb of ram. For AST, this is 30x faster than on CPU only instances.

Reverse proxy of choice was nginx, although I should probably use caddy for simplicity.

### Nginx default upload limit
Nginx has a small file upload limit ~5-10MB. Now that was an issue with video uploads because files are huge. 

Small change to 5Gb in nginx config file to fix that, and is an easy way to implement some limits for freemium plans for example.

```
sudo nano /etc/nginx/nginx.conf
```
```
http {
    ...
    client_max_body_size 5G;
    ...
}

```

# Optionals 
At this point I spent more than 10 hours, and many of it debugging the ytdlp on aws.

Yt-dlp works on local, but on the deployed AWS EC2 instance, the machine is geoblocked by ytdlp, leading to only metadata being recovered. ie ytdlp gives me a "only images are available for download" and mp4 is not pullable. A network proxy would be a workaround, but for videos this would be costly and best self hosted. 

# Thank you