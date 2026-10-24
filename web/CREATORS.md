# Creators

Open `http://localhost:5180/?view=creators`, or select **Creators** in the masthead.

The section is an immersive video feed using the trading desk's shared theme tokens: warm paper surfaces in light mode, charcoal surfaces in dark mode, and the existing orange accent. The sidebar, navigation, investment cards, dialogs, and toasts follow the app theme; video overlays retain white text for contrast. Theme controls use the existing app preference and persist across navigation. Each video occupies one viewport and snaps into place with a native touch swipe or mouse/trackpad scroll. Desktop users can also use arrow keys or navigation buttons. Only the active video loads and plays. Portrait framing fills the feed; the framing control restores the complete landscape source. Tap to pause/resume, double-tap to like, and use the overlay controls for sound and captions. Sound preference carries between videos for the current session.

Asset mentions sit in a shopping card over the video. **Invest** opens an asset sheet with reference quotes, followed by the paper-investment ticket. On mobile these panels open as bottom sheets. Opening a panel pauses playback and closing it resumes a previously playing video. Source attribution, original publication date, and the original video link are available through **Details**. The desktop sidebar and mobile bottom navigation offer saved videos, the paper portfolio, and a return to the trading desk.

The feed uses six downloaded YouTube videos, attributed to their original creators. Each excerpt is 65 seconds long. Original publication dates and source view counts come from the downloaded metadata; the counts are snapshots, not a live engagement feed. The source video and timestamp remain accessible next to each investment ticket.

Asset tags are manually curated from the source captions or chapter metadata. They identify mentions, including educational examples, rather than endorsements. Patrick Boyle's Bitcoin and Strategy tags use the original title, description, and MicroStrategy chapter; the other tags have automatic-caption timestamps.

## Local media

Run from the repository root after the original MP4s and metadata are present in `data/raw/creator_videos/<youtube-id>/`:

```sh
python3 scripts/prepare_creator_feed.py
cd web
npm run dev
```

The preparation script requires FFmpeg. It creates H.264/AAC MP4 excerpts, JPEG posters, WebVTT captions where available, and `src/data/creator-videos.json`. Original English `.en.json3` caption files are optional. All media stays under the gitignored `data/raw/creator_videos/` directory. The curated manifest and preparation script belong in source control.

The Vite development and preview servers expose the clips through `/creator-media/<id>/clip.mp4`, with HTTP byte ranges for playback and seeking. Only the clip, poster, and caption filenames are exposed. When a clip is missing, the feed offers the original YouTube link. A static production deployment needs the media uploaded to hosting/CDN and equivalent media URLs or a server implementing this route; `vite build` alone does not package the downloaded files.

## Paper investing

This application has no brokerage connection. Investments in this section are simulations with $10,000 in starting virtual cash, stored in this browser under `creators-paper-v1`. Each record includes the creator and source video. No real orders are submitted.

Reference prices come from the existing True Markets WebSocket. Confirmation is disabled without a listed asset and fresh quote. Source timestamps older than 60 seconds and messages received more than 30 seconds ago are rejected. Orders debit integer cents, reject invalid amounts and insufficient funds, and estimate fractional units at the reference price. Simulated fills exclude fees and slippage.

Saved videos, followed creators, and likes are stored locally under `creators-saved-v1`, `creators-following-v1`, and `creators-liked-v1`. Likes are personal preferences; the UI does not invent audience counts. Shared links use `?view=creators&video=<youtube-id>`.

## Verification

```sh
cd web
npm run build
npm test
```

Browser verification covers playback and sound, portrait/full-frame modes, captions, double-tap likes, real touch swipes, mouse-wheel and keyboard navigation, pausing inactive videos, category/search filters, saves/follows, clipboard sharing, mobile bottom sheets, investment validation and persistence, responsive layouts, history, and video deep links. Media byte-range serving was verified with the original feed implementation and remains unchanged.
