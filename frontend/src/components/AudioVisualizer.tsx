"use client";

import { useEffect, useRef } from "react";
import type { AudioLevels } from "@/hooks/useAgoraSession";

/** Smooth 60 fps yellow/amber soundwave: rises when Ramesh (mic) or Murf Falcon (agent) speaks.
 *  `pulse` animates it without audio (Demo Sim: a new caption just arrived). */
export function AudioVisualizer({ getLevels, active, pulse = false }: { getLevels: () => AudioLevels; active: boolean; pulse?: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const amp = useRef({ mic: 0, agent: 0 });
  const pulseRef = useRef(pulse);
  pulseRef.current = pulse;

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let raf = 0;
    let t = 0;

    const wave = (w: number, h: number, a: number, freq: number, phase: number, color: string, width: number) => {
      ctx.beginPath();
      for (let x = 0; x <= w; x += 2) {
        const env = Math.sin((Math.PI * x) / w); // taper at both ends
        const y = h / 2 + Math.sin((x / w) * Math.PI * freq + phase) * a * env * (h / 2 - 3);
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.lineCap = "round";
      ctx.stroke();
    };

    const draw = () => {
      t += 0.08;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const lv = active ? getLevels() : { mic: 0, agent: 0 };
      const synth = pulseRef.current ? 0.35 + 0.25 * Math.sin(t * 1.7) : 0;
      amp.current.mic = amp.current.mic * 0.8 + Math.min(1, lv.mic * 2.2) * 0.2;
      amp.current.agent = amp.current.agent * 0.8 + Math.min(1, Math.max(lv.agent * 2.2, synth)) * 0.2;
      const idle = 0.06;
      wave(w, h, Math.max(idle, amp.current.agent), 5, t, "rgba(245, 158, 11, 0.55)", 2); // amber: SyncUp (Murf)
      wave(w, h, Math.max(idle, amp.current.mic), 3.2, -t * 1.3, "rgba(234, 179, 8, 0.95)", 2.6); // yellow: worker
      wave(w, h, Math.max(idle * 0.6, (amp.current.mic + amp.current.agent) / 2.4), 7, t * 0.7, "rgba(250, 204, 21, 0.45)", 1.4);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [getLevels, active]);

  return <canvas ref={canvasRef} className="h-14 w-full" aria-label="Live voice waveform" />;
}
