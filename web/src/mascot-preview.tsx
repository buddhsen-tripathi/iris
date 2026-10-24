// Dev-only mascot sheet: http://localhost:5180/mascot.html (not part of the production build).
import { createRoot } from "react-dom/client";
import { Mascot, type MascotMood } from "@/components/Mascot";
import "./index.css";

const MOODS: { mood: MascotMood; use: string }[] = [
  { mood: "idle", use: "Default · empty states" },
  { mood: "thinking", use: "AI answer streaming" },
  { mood: "curious", use: "Point & ask · first-run tips" },
  { mood: "happy", use: "Upbeat news read" },
  { mood: "cautious", use: "Negative news read · errors" },
  { mood: "sleeping", use: "Offline · AI unavailable" },
];

function Sheet({ dark }: { dark: boolean }) {
  return (
    <section className={dark ? "dark" : ""}>
      <div className="bg-background p-8 text-foreground">
        <div className="mb-6 flex items-baseline gap-3">
          <h1 className="text-xl font-semibold tracking-tight">
            Iris <span className="text-chart-1">Owl</span>
          </h1>
          <span className="kicker">{dark ? "dark" : "light"} theme</span>
        </div>
        <div className="grid grid-cols-6 gap-4">
          {MOODS.map(({ mood, use }) => (
            <figure key={mood} className="flex flex-col items-center gap-2 rounded-lg border bg-card/60 px-3 pt-5 pb-3">
              <Mascot mood={mood} size={104} />
              <figcaption className="text-center">
                <div className="text-[13px] font-semibold capitalize">{mood}</div>
                <div className="text-[10.5px] text-muted-foreground">{use}</div>
              </figcaption>
            </figure>
          ))}
        </div>
        <div className="mt-6 flex items-end gap-8">
          <div className="flex items-end gap-3">
            {[16, 24, 32, 48, 64].map((s) => (
              <Mascot key={s} size={s} mood="idle" />
            ))}
            <span className="kicker">sizes 16–64</span>
          </div>
          <div className="flex items-start gap-2 rounded-lg border bg-popover p-3 shadow-sm">
            <Mascot size={28} mood="thinking" />
            <div className="max-w-xs text-[12.5px]">
              <div className="kicker mb-0.5">Desk analyst</div>
              Reading the order book and the last 5m of flow…
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
            <Mascot size={40} mood="curious" />
            Pick a company on the map to see its connections.
          </div>
        </div>
      </div>
    </section>
  );
}

createRoot(document.getElementById("root")!).render(
  <>
    <Sheet dark={false} />
    <Sheet dark />
  </>,
);
