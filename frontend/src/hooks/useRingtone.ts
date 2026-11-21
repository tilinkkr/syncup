"use client";

import { useEffect } from "react";

/** WebAudio phone ringtone (two-tone trill: 0.4 s on, 0.2 s off, 0.4 s on, 2 s pause). No audio files needed. */
export function useRingtone(active: boolean) {
  useEffect(() => {
    if (!active) return;
    let ctx: AudioContext | null = null;
    try {
      ctx = new AudioContext();
    } catch {
      return;
    }
    void ctx.resume().catch(() => undefined);
    const gain = ctx.createGain();
    gain.gain.value = 0;
    gain.connect(ctx.destination);
    const oscs = [440, 480].map((f) => {
      const o = ctx!.createOscillator();
      o.frequency.value = f;
      o.connect(gain);
      o.start();
      return o;
    });
    const burst = (at: number) => {
      gain.gain.setValueAtTime(0, at);
      gain.gain.linearRampToValueAtTime(0.07, at + 0.02);
      gain.gain.setValueAtTime(0.07, at + 0.38);
      gain.gain.linearRampToValueAtTime(0, at + 0.4);
    };
    const schedule = () => {
      if (!ctx) return;
      const t = ctx.currentTime + 0.05;
      burst(t);
      burst(t + 0.6);
    };
    schedule();
    const id = setInterval(schedule, 3000);
    return () => {
      clearInterval(id);
      oscs.forEach((o) => o.stop());
      void ctx?.close().catch(() => undefined);
    };
  }, [active]);
}
