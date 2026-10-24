import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { Mascot, useMascotOn, type MascotMood } from "./Mascot";

// Three first-run tips from the Iris Owl, shown once per browser. Skipped entirely when the owl is off.

const STORAGE_KEY = "owl-tips";
const TIPS: { mood: MascotMood; title: string; body: string }[] = [
  { mood: "curious", title: "Hoot, I'm the Iris Owl.", body: "⌥-click anything on the desk (a price, a headline, a trade) and ask me about it." },
  { mood: "idle", title: "Need a deeper read?", body: "⌘J opens the desk analyst. It reads your screen and can pull candles, funding and news." },
  { mood: "happy", title: "Make the desk yours", body: "Drag the lines between panels to resize, and click a panel's title to collapse it." },
];

export function OwlTips() {
  const owl = useMascotOn();
  const [step, setStep] = useState<number | null>(null);

  useEffect(() => {
    if (!owl || localStorage.getItem(STORAGE_KEY) === "done") return;
    const id = setTimeout(() => setStep(0), 1200);
    return () => clearTimeout(id);
  }, [owl]);

  if (!owl || step === null) return null;
  const tip = TIPS[step];
  const finish = () => {
    localStorage.setItem(STORAGE_KEY, "done");
    setStep(null);
  };
  const last = step === TIPS.length - 1;

  return (
    <div
      data-ask-ignore
      role="dialog"
      aria-label="Tip from the Iris Owl"
      className="rise fixed bottom-10 left-4 z-30 flex w-[320px] gap-3 rounded-xl border bg-popover p-3 pr-8 text-popover-foreground shadow-xl"
    >
      <Mascot size={52} mood={tip.mood} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold">{tip.title}</p>
        <p className="mt-0.5 text-[12px] leading-snug text-muted-foreground">{tip.body}</p>
        <div className="mt-2.5 flex items-center gap-2">
          <span className="flex gap-1" aria-label={`Tip ${step + 1} of ${TIPS.length}`}>
            {TIPS.map((_, i) => (
              <i key={i} className={`size-1.5 rounded-full ${i === step ? "bg-chart-1" : "bg-muted"}`} />
            ))}
          </span>
          <button onClick={finish} className="ml-auto text-[11px] text-muted-foreground hover:text-foreground">
            Skip
          </button>
          <button
            onClick={() => (last ? finish() : setStep(step + 1))}
            className="rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-foreground hover:opacity-90"
          >
            {last ? "Got it" : "Next"}
          </button>
        </div>
      </div>
      <button onClick={finish} aria-label="Close tips" className="absolute top-2 right-2 text-muted-foreground hover:text-foreground">
        <X className="size-3.5" />
      </button>
    </div>
  );
}
