import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Bookmark, ChartNoAxesCombined, Check, ChevronRight, ExternalLink, Film, Heart, Home, Info, Moon, Music2, Plus, Search, Share2, ShoppingBag, SlidersHorizontal, Sun, Users, Wallet, X } from 'lucide-react';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { z } from 'zod';
import type { Catalog } from '@/hooks/useCatalog';
import { useNow, useTopic } from '@/hooks/useMarket';
import { useTheme } from '@/hooks/useTheme';
import { amountInCents, createPaperOrder, creatorVideos, freshQuote, mediaURL, paperBalance, paperOrdersSchema, type CreatorVideo, type Mention, type PaperOrder } from '@/lib/creators';
import { compact, price } from '@/lib/format';
import { topics, type LivePrice } from '@/lib/tm';
import { cn } from '@/lib/utils';
import { AssetIcon } from './ui';
import { CreatorPlayer } from './creator-player';
import './creators.css';
import './creator-feed.css';

const dollars = (cents: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(cents / 100);
const minute = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
const published = (date: string) => new Date(`${date}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
const stringList = z.array(z.string());

function readStrings(key: string) {
  try { return stringList.parse(JSON.parse(localStorage.getItem(key) ?? '[]')); } catch { return []; }
}
function readOrders() {
  try { return paperOrdersSchema.parse(JSON.parse(localStorage.getItem('creators-paper-v1') ?? '[]')); } catch { return []; }
}

function useCreatorQuote(symbol: string, catalog: Catalog) {
  const listed = catalog.bySymbol.has(symbol);
  const quote = useTopic<LivePrice>(listed ? topics.price(symbol, catalog.classOf(symbol)) : null);
  const now = useNow();
  return { quote: freshQuote(quote.value?.data, quote.value?.receivedAt, now), listed };
}

function MentionRow({ mention, catalog, onInvest }: { mention: Mention; catalog: Catalog; onInvest: () => void }) {
  const { quote, listed } = useCreatorQuote(mention.symbol, catalog);
  return <button className="creator-asset" onClick={onInvest} aria-label={`Invest in ${mention.symbol}`}>
    <AssetIcon symbol={mention.symbol} src={catalog.bySymbol.get(mention.symbol)?.icon} />
    <span><strong>{mention.symbol}</strong><small>{mention.name}</small></span>
    <span className="creator-asset-price"><strong>{quote === null ? '—' : `$${price(quote)}`}</strong><small>{!listed ? 'Not listed on desk' : quote === null ? 'Quote unavailable' : 'Live reference'}</small></span>
    <ChevronRight size={15} />
  </button>;
}

function CreatorAvatar({ video, className }: { video: CreatorVideo; className?: string }) {
  return <img className={cn('shorts-avatar', className)} src={mediaURL(video.id, 'poster.jpg')} alt="" loading="lazy"/>;
}

function CreatorSheet({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="creator-sheet" aria-labelledby={id} onClose={onClose} onClick={event => { if (event.target === dialog.current) onClose(); }}>
    <div className="creator-sheet-handle"/>
    <header><h2 id={id}>{title}</h2><button aria-label={`Close ${title.toLowerCase()}`} onClick={onClose}><X size={21}/></button></header>
    {children}
  </dialog>;
}

function InvestmentTicket({ video, mention, catalog, orders, onOrder, onClose, onDesk }: {
  video: CreatorVideo; mention: Mention; catalog: Catalog; orders: PaperOrder[];
  onOrder: (order: PaperOrder) => boolean; onClose: () => void; onDesk: (symbol: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const { quote, listed } = useCreatorQuote(mention.symbol, catalog);
  const [amount, setAmount] = useState('50');
  const [error, setError] = useState('');
  const [complete, setComplete] = useState<PaperOrder | null>(null);
  const balance = paperBalance(orders);
  const cents = amountInCents(amount);
  useEffect(() => { dialog.current?.showModal(); }, []);
  const confirm = () => {
    const result = createPaperOrder({ amount, price: quote, balanceCents: balance, symbol: mention.symbol, video });
    if (result.error) { setError(result.error); return; }
    if (result.order && onOrder(result.order)) { setComplete(result.order); setError(''); }
    else setError('Your browser could not save this investment. Please allow local storage and try again.');
  };
  return <dialog ref={dialog} className="creator-ticket" onClose={onClose} onClick={event => { if (event.target === dialog.current) onClose(); }} aria-labelledby="creator-ticket-title">
    <header><span className="kicker"><Wallet size={14}/> Paper investing</span><button onClick={onClose} aria-label="Close investment ticket"><X size={18}/></button></header>
    {complete ? <div className="creator-ticket-success"><span><Check size={26}/></span><h2 id="creator-ticket-title">Added to your paper portfolio.</h2><p>{dollars(complete.amountCents)} in {complete.symbol}</p><small>{complete.shares.toFixed(6)} units at ${price(complete.price)} · simulated fill</small><button className="creator-primary" onClick={onClose}>Keep exploring <ArrowRight size={16}/></button></div> : <>
      <div className="creator-ticket-asset"><AssetIcon symbol={mention.symbol} src={catalog.bySymbol.get(mention.symbol)?.icon}/><div><h2 id="creator-ticket-title">Invest in {mention.symbol}</h2><p>{mention.name}</p></div><strong>{quote === null ? '—' : `$${price(quote)}`}</strong></div>
      <p className="creator-ticket-context">Mentioned by {video.creator} · <a href={`${video.sourceURL}&t=${mention.at}`} target="_blank" rel="noreferrer">View source at {minute(mention.at)} <ExternalLink size={11}/></a></p>
      <label className="creator-amount-label" htmlFor="creator-invest-amount">Amount in USD</label>
      <div className="creator-amount"><span>$</span><input id="creator-invest-amount" inputMode="decimal" value={amount} onChange={event => { setAmount(event.target.value); setError(''); }} autoComplete="off" /></div>
      <div className="creator-quick-amounts">{['25','50','100','250'].map(value => <button key={value} aria-pressed={amount === value} onClick={() => { setAmount(value); setError(''); }}>${value}</button>)}</div>
      <dl className="creator-ticket-details"><div><dt>Available paper cash</dt><dd>{dollars(balance)}</dd></div><div><dt>Estimated units</dt><dd>{quote !== null && cents !== null ? (cents/100/quote).toFixed(6) : '—'}</dd></div><div><dt>Quote</dt><dd>{!listed ? 'Not available on this desk' : quote === null ? 'Waiting for a fresh quote' : 'Live market reference'}</dd></div></dl>
      <p className="creator-paper-note">Practice with virtual cash. No real money is invested. Simulated fills use the reference price; fees and slippage are excluded.</p>
      {error && <p className="creator-error" role="alert">{error}</p>}
      <button className="creator-primary" disabled={quote === null} onClick={confirm}>Confirm paper investment <ArrowRight size={16}/></button>
      {listed && <button className="creator-desk-link" onClick={() => onDesk(mention.symbol)}>Research {mention.symbol} on the trading desk <ExternalLink size={13}/></button>}
    </>}
  </dialog>;
}

export function Creators({ catalog, onDesk }: { catalog: Catalog; onDesk: (symbol: string) => void }) {
  const { theme, toggle } = useTheme();
  const [category, setCategory] = useState('all');
  const [collection, setCollection] = useState('discover');
  const [search, setSearch] = useState('');
  const [saved, setSaved] = useState(() => readStrings('creators-saved-v1'));
  const [following, setFollowing] = useState(() => readStrings('creators-following-v1'));
  const [orders, setOrders] = useState(readOrders);
  const [activeId, setActiveId] = useState(() => new URLSearchParams(location.search).get('video') ?? creatorVideos[0].id);
  const [ticket, setTicket] = useState<{ video: CreatorVideo; mention: Mention } | null>(null);
  const [notice, setNotice] = useState('');
  const [liked, setLiked] = useState(() => readStrings('creators-liked-v1'));
  const [muted, setMuted] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);
  const [assetsVideo, setAssetsVideo] = useState<CreatorVideo | null>(null);
  const [sourceVideo, setSourceVideo] = useState<CreatorVideo | null>(null);
  const [walletOpen, setWalletOpen] = useState(false);
  const feed = useRef<HTMLDivElement>(null);
  const initialScrollDone = useRef(false);
  const query = search.trim().toLowerCase();
  const videos = creatorVideos.filter(video => (category === 'all' || video.category === category)
    && (collection !== 'saved' || saved.includes(video.id)) && (collection !== 'following' || following.includes(video.creator))
    && `${video.creator} ${video.title} ${video.mentions.map(m => `${m.symbol} ${m.name}`).join(' ')}`.toLowerCase().includes(query));
  const active = videos.find(video => video.id === activeId) ?? videos[0];
  const activeIndex = videos.findIndex(video => video.id === active?.id);
  const videoIds = videos.map(video => video.id).join(',');

  useEffect(() => {
    const root = feed.current;
    if (!root) return;
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting && entry.target instanceof HTMLElement && entry.target.dataset.video) setActiveId(entry.target.dataset.video);
    }, { root, threshold: 0.65 });
    root.querySelectorAll('[data-video]').forEach(element => observer.observe(element));
    if (!initialScrollDone.current) {
      const video = new URLSearchParams(location.search).get('video');
      const story = Array.from(root.querySelectorAll<HTMLElement>('[data-video]')).find(element => element.dataset.video === video);
      if (story) root.scrollTop = story.offsetTop;
      initialScrollDone.current = true;
    }
    return () => observer.disconnect();
  }, [videoIds]);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 3500); return () => clearTimeout(timer); }, [notice]);

  const toggleItem = (key: string, values: string[], item: string, update: (next: string[]) => void) => {
    const next = values.includes(item) ? values.filter(value => value !== item) : [...values, item];
    try { localStorage.setItem(key, JSON.stringify(next)); update(next); } catch { setNotice('Your browser could not save this preference.'); }
  };
  const jump = (id: string) => {
    const root = feed.current;
    const story = Array.from(root?.querySelectorAll<HTMLElement>('[data-video]') ?? []).find(element => element.dataset.video === id);
    if (root && story) { root.scrollTo({ top: story.offsetTop, behavior: 'instant' }); setActiveId(id); }
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || ticket || assetsVideo || sourceVideo || walletOpen) return;
      const next = event.key === 'ArrowDown' ? videos[activeIndex + 1] : event.key === 'ArrowUp' ? videos[activeIndex - 1] : undefined;
      if (next) { event.preventDefault(); jump(next.id); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [activeIndex, videoIds, ticket, assetsVideo, sourceVideo, walletOpen]);
  const changeCategory = (next: string) => { setCategory(next); if (feed.current) feed.current.scrollTop = 0; };
  const share = async (video: CreatorVideo) => {
    const url = new URL(location.href); url.searchParams.set('view', 'creators'); url.searchParams.set('video', video.id);
    try { await navigator.clipboard.writeText(url.toString()); setNotice('Video link copied.'); } catch { setNotice('Could not copy the link. Use the original video link below.'); }
  };
  const saveOrder = (order: PaperOrder) => {
    const next = [...orders, order];
    if (paperBalance(next) < 0) return false;
    try { localStorage.setItem('creators-paper-v1', JSON.stringify(next)); setOrders(next); return true; } catch { return false; }
  };

  const chooseCollection = (next: string) => {
    setCollection(next);
    if (feed.current) feed.current.scrollTop = 0;
  };
  const openInvestment = (video: CreatorVideo, mention: Mention) => {
    setAssetsVideo(null);
    setTicket({ video, mention });
  };

  return <main className="shorts-shell" aria-label="Creators">
    <aside className="shorts-sidebar">
      <button className="shorts-brand" onClick={() => onDesk('BTC')} aria-label="Iris trading desk">I<span>ris</span><small>CREATORS</small></button>
      <button className="shorts-theme-toggle" onClick={toggle} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>{theme === 'dark' ? <Sun size={14}/> : <Moon size={14}/>}</button>
      <label className="shorts-search"><Search size={18}/><input value={search} onChange={event => { setSearch(event.target.value); if (feed.current) feed.current.scrollTop = 0; }} placeholder="Search creators or tickers" aria-label="Search creators and assets"/>{search && <button onClick={() => setSearch('')} aria-label="Clear creator search"><X size={15}/></button>}</label>
      <nav className="shorts-navigation" aria-label="Creator navigation">
        <button aria-current={collection === 'discover' ? 'page' : undefined} onClick={() => chooseCollection('discover')}><Home size={23}/> For you</button>
        <button aria-current={collection === 'following' ? 'page' : undefined} onClick={() => chooseCollection('following')}><Users size={23}/> Following</button>
        <button aria-current={collection === 'saved' ? 'page' : undefined} onClick={() => chooseCollection('saved')}><Bookmark size={23}/> Saved <small>{saved.length}</small></button>
        <button onClick={() => onDesk('BTC')}><ChartNoAxesCombined size={23}/> Trading desk <ExternalLink size={13}/></button>
      </nav>
      <div className="shorts-category"><span>YOUR INTERESTS</span><div>{[{id:'all',label:'All'},{id:'stocks',label:'Stocks'},{id:'crypto',label:'Crypto'}].map(item => <button key={item.id} aria-pressed={category === item.id} onClick={() => changeCategory(item.id)}>{item.label}</button>)}</div></div>
      <section className="shorts-voices"><h2>CREATORS TO KNOW</h2>{creatorVideos.slice(0,4).map(video => <button key={video.id} onClick={() => { chooseCollection('discover'); setCategory('all'); setSearch(video.creator); }}><CreatorAvatar video={video}/><span><strong>{video.creator}</strong><small>{video.category === 'stocks' ? 'Stocks & investing' : 'Crypto & markets'}</small></span>{following.includes(video.creator) && <Check size={13}/>}</button>)}</section>
      <button className="shorts-wallet" onClick={() => setWalletOpen(true)}><span><Wallet size={17}/> Your paper portfolio</span><strong>{dollars(paperBalance(orders))}<ChevronRight size={17}/></strong><small>Virtual cash available</small></button>
      <p className="shorts-sidebar-note">Find your perspective.<br/>Make your own moves.</p>
    </aside>

    <section className="shorts-stage" aria-label="Creator video feed">
      {active && <img className="shorts-stage-backdrop" src={mediaURL(active.id, 'poster.jpg')} alt=""/>}
      <div className="shorts-topbar">
        <button className="shorts-mobile-back" onClick={() => onDesk('BTC')} aria-label="Back to trading desk"><ArrowLeft size={22}/></button>
        <div className="shorts-feed-tabs" aria-label="Feed collection">{[{id:'following',label:'Following'},{id:'discover',label:'For you'},{id:'saved',label:'Saved'}].map(item => <button key={item.id} aria-pressed={collection === item.id} onClick={() => chooseCollection(item.id)}>{item.label}</button>)}</div>
        <button className="shorts-mobile-search" aria-label={searchOpen ? 'Close feed search' : 'Open feed search'} onClick={() => setSearchOpen(value => !value)}>{searchOpen ? <X size={22}/> : <Search size={23}/>}</button>
      </div>
      <button className="shorts-mobile-theme" onClick={toggle} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>{theme === 'dark' ? <Sun size={16}/> : <Moon size={16}/>}</button>
      {searchOpen && <div className="shorts-mobile-search-panel"><label><Search size={17}/><input autoFocus value={search} onChange={event => { setSearch(event.target.value); if (feed.current) feed.current.scrollTop = 0; }} placeholder="Creator, company, or ticker" aria-label="Search feed"/>{search && <button onClick={() => setSearch('')} aria-label="Clear feed search"><X size={16}/></button>}</label><div>{[{id:'all',label:'All videos'},{id:'stocks',label:'Stocks'},{id:'crypto',label:'Crypto'}].map(item => <button key={item.id} aria-pressed={category === item.id} onClick={() => changeCategory(item.id)}>{item.label}</button>)}</div></div>}
      {(query || category !== 'all') && <div className="shorts-filter-status"><SlidersHorizontal size={12}/>{query || category}<button onClick={() => { setSearch(''); changeCategory('all'); }} aria-label="Clear feed filters"><X size={13}/></button></div>}

      <div className="shorts-feed" ref={feed} tabIndex={0} aria-label="Scroll videos" onKeyDown={event => {
        if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || ticket || assetsVideo || sourceVideo || walletOpen) return;
        const next = event.key === 'ArrowDown' ? videos[activeIndex+1] : event.key === 'ArrowUp' ? videos[activeIndex-1] : undefined;
        if (next) { event.preventDefault(); jump(next.id); }
      }}>
        {videos.map(video => <article key={video.id} data-video={video.id} className="shorts-story" aria-label={`${video.creator} video`}>
          <div className="shorts-frame">
            <CreatorPlayer video={video} active={video.id === active?.id} muted={muted} suspended={!!(ticket || assetsVideo || sourceVideo || walletOpen)} onMute={() => setMuted(value => !value)} onLike={() => { if (!liked.includes(video.id)) toggleItem('creators-liked-v1', liked, video.id, setLiked); }}/>
            <div className="shorts-gradient"/>
            <div className="shorts-actions">
              <button className="shorts-follow-avatar" aria-label={following.includes(video.creator) ? `Unfollow ${video.creator}` : `Follow ${video.creator}`} aria-pressed={following.includes(video.creator)} onClick={() => toggleItem('creators-following-v1', following, video.creator, setFollowing)}><CreatorAvatar video={video}/><span>{following.includes(video.creator) ? <Check size={12}/> : <Plus size={14}/>}</span></button>
              <button className={cn(liked.includes(video.id) && 'is-liked')} aria-label={liked.includes(video.id) ? `Unlike ${video.creator} video` : `Like ${video.creator} video`} aria-pressed={liked.includes(video.id)} onClick={() => toggleItem('creators-liked-v1', liked, video.id, setLiked)}><Heart size={31} fill="currentColor" strokeWidth={1.5}/><span>{liked.includes(video.id) ? 'Liked' : 'Like'}</span></button>
              <button className={cn(saved.includes(video.id) && 'is-saved')} aria-label={saved.includes(video.id) ? `Unsave ${video.creator} video` : `Save ${video.creator} video`} aria-pressed={saved.includes(video.id)} onClick={() => toggleItem('creators-saved-v1', saved, video.id, setSaved)}><Bookmark size={29} fill="currentColor" strokeWidth={1.5}/><span>{saved.includes(video.id) ? 'Saved' : 'Save'}</span></button>
              <button aria-label={`Share ${video.creator} video`} onClick={() => void share(video)}><Share2 size={29} fill="currentColor" strokeWidth={1.5}/><span>Share</span></button>
              <button aria-label={`Details for ${video.creator} video`} onClick={() => setSourceVideo(video)}><Info size={26}/><span>Details</span></button>
            </div>
            <div className="shorts-story-content">
              <button className="shorts-asset-teaser" onClick={() => setAssetsVideo(video)}><ShoppingBag size={14}/><strong>{video.mentions.length} assets in this video</strong><ChevronRight size={13}/></button>
              <div className="shorts-creator-line"><strong>{video.creator}</strong><button aria-pressed={following.includes(video.creator)} onClick={() => toggleItem('creators-following-v1', following, video.creator, setFollowing)}>{following.includes(video.creator) ? 'Following' : 'Follow'}</button></div>
              <p className="shorts-description">{video.summary} <button onClick={() => setSourceVideo(video)}>more</button></p>
              <div className="shorts-audio"><Music2 size={13}/><span>Original audio · {video.creator}</span><span className="shorts-excerpt">1:05 excerpt</span></div>
              <div className="shorts-invest-strip"><div className="shorts-invest-heading"><span><ShoppingBag size={14}/> Invest in what you discover</span><small>PAPER</small></div><div className="shorts-invest-assets">{video.mentions.slice(0,3).map(mention => <button key={mention.symbol} aria-label={`Invest in ${mention.symbol}`} onClick={() => openInvestment(video, mention)}><AssetIcon symbol={mention.symbol} src={catalog.bySymbol.get(mention.symbol)?.icon}/><strong>{mention.symbol}</strong></button>)}<button className="shorts-invest-cta" aria-label={`Explore assets mentioned by ${video.creator}`} onClick={() => setAssetsVideo(video)}>Invest <ArrowRight size={13}/></button></div></div>
            </div>
          </div>
        </article>)}
        {!videos.length && <div className="shorts-empty"><Film size={36}/><h1>{collection === 'saved' ? 'Save your next idea.' : collection === 'following' ? 'Find your people.' : 'No videos found.'}</h1><p>{collection === 'saved' ? 'Tap the bookmark on a video to keep it here.' : collection === 'following' ? 'Follow a creator and their videos will appear here.' : 'Try a different creator, ticker, or category.'}</p><button onClick={() => { chooseCollection('discover'); setSearch(''); setCategory('all'); }}>Explore the feed <ArrowRight size={16}/></button></div>}
      </div>
      <div className="shorts-feed-controls"><span>{videos.length ? String(activeIndex+1).padStart(2,'0') : '00'}<small> / {String(videos.length).padStart(2,'0')}</small></span><button disabled={activeIndex <= 0} aria-label="Previous video" onClick={() => { const previous = videos[activeIndex-1]; if (previous) jump(previous.id); }}><ArrowUp size={23}/></button><button disabled={activeIndex >= videos.length-1} aria-label="Next video" onClick={() => { const next = videos[activeIndex+1]; if (next) jump(next.id); }}><ArrowDown size={23}/></button><p>Scroll to explore</p></div>
      <span className="shorts-stage-note">A little perspective goes a long way.</span>
      <button className="shorts-practice-pill" onClick={() => setWalletOpen(true)}><Wallet size={13}/> Paper portfolio <ChevronRight size={13}/></button>
    </section>

    <nav className="shorts-mobile-nav" aria-label="Mobile creator navigation"><button aria-current={collection === 'discover' ? 'page' : undefined} onClick={() => chooseCollection('discover')}><Home size={22} fill={collection === 'discover' ? 'currentColor' : 'none'}/><span>For you</span></button><button onClick={() => onDesk('BTC')}><ChartNoAxesCombined size={22}/><span>Markets</span></button><button aria-current={collection === 'saved' ? 'page' : undefined} onClick={() => chooseCollection('saved')}><Bookmark size={21} fill={collection === 'saved' ? 'currentColor' : 'none'}/><span>Saved</span></button><button onClick={() => setWalletOpen(true)}><Wallet size={22}/><span>Portfolio</span></button></nav>

    {assetsVideo && <CreatorSheet title="In this video" onClose={() => setAssetsVideo(null)}><div className="shorts-sheet-creator"><CreatorAvatar video={assetsVideo}/><div><strong>{assetsVideo.creator}</strong><p>{assetsVideo.mentions.length} asset mentions · Paper investing</p></div></div><div className="shorts-sheet-assets">{assetsVideo.mentions.map(mention => <MentionRow key={mention.symbol} mention={mention} catalog={catalog} onInvest={() => openInvestment(assetsVideo, mention)}/>)}</div><p className="shorts-sheet-note">Mentions include educational examples. Choose an asset to review your paper investment.</p></CreatorSheet>}
    {sourceVideo && <CreatorSheet title="About this video" onClose={() => setSourceVideo(null)}><div className="shorts-sheet-creator"><CreatorAvatar video={sourceVideo}/><div><strong>{sourceVideo.creator}</strong><p>{compact(sourceVideo.views)} source views · {published(sourceVideo.publishedAt)}</p></div></div><h3 className="shorts-source-title">{sourceVideo.title}</h3><p className="shorts-source-description">{sourceVideo.summary}</p><a className="shorts-source-link" href={`${sourceVideo.sourceURL}&t=${sourceVideo.clipStart}`} target="_blank" rel="noreferrer">Watch the original at {minute(sourceVideo.clipStart)} <ExternalLink size={14}/></a><p className="shorts-sheet-note">This is an excerpt from the original video. Asset tags identify mentions, not buy recommendations. Creator opinions are their own.</p></CreatorSheet>}
    {walletOpen && <CreatorSheet title="Your paper portfolio" onClose={() => setWalletOpen(false)}><div className="shorts-wallet-balance"><span>Available virtual cash</span><strong>{dollars(paperBalance(orders))}</strong><small>Practice mode · No real orders</small></div><div className="shorts-portfolio-orders">{orders.length ? [...orders].reverse().map(order => <div key={order.id}><span><strong>{order.symbol}</strong><small>Via {order.creator}</small></span><span><strong>{dollars(order.amountCents)}</strong><small>{order.shares.toFixed(6)} units</small></span></div>) : <p>Your ideas start here. Explore an asset in the feed to make your first paper investment.</p>}</div></CreatorSheet>}
    {notice && <div className="creator-toast" role="status">{notice}</div>}
    {ticket && <InvestmentTicket key={`${ticket.video.id}-${ticket.mention.symbol}`} video={ticket.video} mention={ticket.mention} catalog={catalog} orders={orders} onOrder={saveOrder} onClose={() => setTicket(null)} onDesk={onDesk}/>}
  </main>;
}
