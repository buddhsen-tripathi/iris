import json
import subprocess
from pathlib import Path

root = Path('data/raw/creator_videos')
selections = [
    ('bNIAi9Sm3rY', 428, 65, 'stocks', 'Your first investment starts here.', 'Individual stocks or a fund? Humphrey walks through the choices.', [('AAPL','Apple',442),('MSFT','Microsoft',442),('NVDA','NVIDIA',442),('TSLA','Tesla',445)]),
    ('inI0SC3Zj4A', 136, 65, 'stocks', 'When a company becomes a Bitcoin bet.', 'Patrick explores MicroStrategy’s pivot and the Bitcoin treasury trade.', [('MSTR','Strategy',136),('BTC','Bitcoin',0)]),
    ('IZWrAbFveSA', 260, 65, 'crypto', 'Start with the Bitcoin basics.', 'Brian’s introduction to how Bitcoin became an investable asset.', [('BTC','Bitcoin',268)]),
    ('Nv5CiRSCVxA', 51, 65, 'stocks', 'Own the market. Understand the trade-off.', 'Ben explains market indexes and the companies behind them.', [('AAPL','Apple',89),('MSFT','Microsoft',89)]),
    ('14HIIUjOLGY', 232, 65, 'crypto', 'Read the chart before the trade.', 'A practical introduction to price trends and candlestick charts.', [('BTC','Bitcoin',240)]),
    ('gRrHFoDzRHs', 90, 65, 'stocks', 'A different way to look at the market.', 'Andrei discusses index investing and the broader stock market.', [('VOO','Vanguard S&P 500 ETF',98)]),
]

def timestamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}'

records = []
for video_id, start, duration, category, headline, summary, mentions in selections:
    folder = root / video_id
    info = json.loads((folder/f'{video_id}.info.json').read_text())
    clip = folder/f'{video_id}.clip.mp4'
    if not clip.exists():
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss',str(start),'-i',str(folder/f'{video_id}.mp4'),'-t',str(duration),'-c:v','libx264','-preset','veryfast','-crf','24','-c:a','aac','-b:a','96k','-movflags','+faststart','-y',str(clip)],check=True)
    poster = folder/f'{video_id}.poster.jpg'
    if not poster.exists():
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss',str(start+3),'-i',str(folder/f'{video_id}.mp4'),'-frames:v','1','-q:v','2','-y',str(poster)],check=True)
    captions = folder/f'{video_id}.en.json3'
    cues = []
    if captions.exists():
        for event in json.loads(captions.read_text()).get('events',[]):
            text = ''.join(s.get('utf8','') for s in event.get('segs',[])).strip()
            cue_start = event.get('tStartMs',0)/1000-start
            cue_end = cue_start+event.get('dDurationMs',0)/1000
            if text and cue_end>0 and cue_start<duration:
                cues.append(f'{timestamp(max(0,cue_start))} --> {timestamp(min(duration,cue_end))}\n{text}')
        (folder/f'{video_id}.captions.vtt').write_text('WEBVTT\n\n'+'\n\n'.join(cues)+'\n')
    records.append({
        'id': video_id, 'creator': info['channel'], 'channelURL': info['channel_url'],
        'title': info['title'], 'headline': headline, 'summary': summary, 'category': category,
        'publishedAt': f"{info['upload_date'][:4]}-{info['upload_date'][4:6]}-{info['upload_date'][6:]}",
        'views': info.get('view_count',0), 'sourceURL': f'https://www.youtube.com/watch?v={video_id}',
        'clipStart': start, 'clipDuration': duration, 'hasCaptions':bool(cues),
        'mentions': [{'symbol':symbol,'name':name,'at':at,'evidence':'Source chapter' if video_id=='inI0SC3Zj4A' else 'Auto-caption mention'} for symbol,name,at in mentions],
    })
    print(video_id,'ready',flush=True)
destination=Path('web/src/data/creator-videos.json')
destination.parent.mkdir(parents=True,exist_ok=True)
destination.write_text(json.dumps(records,indent=2,ensure_ascii=False)+'\n')
