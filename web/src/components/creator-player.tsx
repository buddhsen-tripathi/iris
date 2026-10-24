import { Captions, Film, Heart, Maximize2, Minimize2, Pause, Play, Volume2, VolumeX } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { mediaURL, type CreatorVideo } from '@/lib/creators';
import { cn } from '@/lib/utils';

const time = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

export function CreatorPlayer({ video, active, muted, suspended, onMute, onLike }: {
  video: CreatorVideo; active: boolean; muted: boolean; suspended: boolean; onMute: () => void; onLike: () => void;
}) {
  const player = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);
  const [paused, setPaused] = useState(false);
  const [loading, setLoading] = useState(true);
  const [fit, setFit] = useState(false);
  const [captions, setCaptions] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(video.clipDuration);
  const [heartVisible, setHeartVisible] = useState(false);
  const resumeAfterSheet = useRef(false);

  useEffect(() => {
    const element = player.current;
    if (!element) return;
    if (active) void element.play().catch(() => setPaused(true));
    else element.pause();
    const pause = () => { if (document.hidden) element.pause(); };
    document.addEventListener('visibilitychange', pause);
    return () => document.removeEventListener('visibilitychange', pause);
  }, [active]);

  useEffect(() => {
    const element = player.current;
    if (!element || !active) return;
    if (suspended) {
      resumeAfterSheet.current = !element.paused;
      element.pause();
    } else if (resumeAfterSheet.current) {
      resumeAfterSheet.current = false;
      void element.play().catch(() => setPaused(true));
    }
  }, [suspended, active]);

  useEffect(() => {
    if (!heartVisible) return;
    const timer = setTimeout(() => setHeartVisible(false), 700);
    return () => clearTimeout(timer);
  }, [heartVisible]);

  useEffect(() => {
    const track = player.current?.textTracks[0];
    const element = player.current?.querySelector('track');
    if (!track) return;
    track.mode = captions ? 'showing' : 'hidden';
    const positionCaptions = () => {
      for (const cue of Array.from(track.cues ?? [])) {
        if (cue instanceof VTTCue) { cue.snapToLines = false; cue.line = 52; cue.position = 50; cue.size = 82; }
      }
    };
    positionCaptions();
    element?.addEventListener('load', positionCaptions);
    return () => element?.removeEventListener('load', positionCaptions);
  }, [captions, active]);

  const togglePlayback = () => {
    const element = player.current;
    if (!element) return;
    if (element.paused) void element.play().catch(() => setPaused(true));
    else element.pause();
  };

  return <>
    <img className="shorts-poster" src={mediaURL(video.id, 'poster.jpg')} alt="" loading="lazy"/>
    {failed ? <div className="shorts-media-error"><Film size={30}/><strong>This excerpt is unavailable.</strong><a href={`${video.sourceURL}&t=${video.clipStart}`} target="_blank" rel="noreferrer">Watch the original video</a></div> : <>
      <video ref={player} className={cn('shorts-video', fit && 'show-full-frame')} src={active ? mediaURL(video.id, 'clip.mp4') : undefined}
        poster={mediaURL(video.id, 'poster.jpg')} playsInline muted={muted} loop preload="none"
        onError={() => setFailed(true)} onWaiting={() => setLoading(true)} onCanPlay={() => setLoading(false)}
        onPlay={() => setPaused(false)} onPause={() => setPaused(true)}
        onLoadedMetadata={event => { setDuration(event.currentTarget.duration); setCurrent(0); }}
        onTimeUpdate={event => setCurrent(event.currentTarget.currentTime)} aria-label={`${video.creator}: ${video.title}`}>
        {video.hasCaptions && <track kind="captions" srcLang="en" label="English (automatic)" src={mediaURL(video.id, 'captions.vtt')}/>}
      </video>
      <button className="shorts-play-surface" onClick={togglePlayback} onDoubleClick={() => { onLike(); setHeartVisible(true); }} aria-label={paused ? 'Play video' : 'Pause video'} tabIndex={active ? 0 : -1}>
        {paused && !loading && <span className="shorts-paused"><Play size={55} fill="currentColor" strokeWidth={0}/></span>}
        {loading && active && <span className="shorts-loading" aria-label="Loading video"/>}
      </button>
      {heartVisible && <span className="shorts-heart-burst" aria-hidden><Heart size={100} fill="currentColor" strokeWidth={0}/></span>}
      <div className="shorts-player-tools">
        {video.hasCaptions && <button onClick={() => setCaptions(value => !value)} aria-label="Toggle captions" aria-pressed={captions}><Captions size={19}/></button>}
        <button onClick={() => setFit(value => !value)} aria-label={fit ? 'Fill video frame' : 'Show full video frame'}>{fit ? <Minimize2 size={18}/> : <Maximize2 size={18}/>}</button>
        <button onClick={onMute} aria-label={muted ? 'Unmute video' : 'Mute video'}>{muted ? <VolumeX size={20}/> : <Volume2 size={20}/>}</button>
      </div>
      <div className="shorts-progress"><span>{time(current)} / {time(duration)}</span><input type="range" min="0" max={duration} step="0.1" value={Math.min(current, duration)} aria-label={`Seek ${video.creator} video`}
        style={{ backgroundSize: `${duration ? current / duration * 100 : 0}% 100%` }}
        onChange={event => { const next = Number(event.target.value); if (player.current) player.current.currentTime = next; setCurrent(next); }}/></div>
      <span className="shorts-playback-hint"><Pause size={10}/> Tap to pause</span>
    </>}
  </>;
}
