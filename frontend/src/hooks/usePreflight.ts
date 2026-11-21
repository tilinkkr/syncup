"use client";

import { useCallback, useEffect, useState } from "react";
import { BACKEND_URL } from "@/lib/config";
import type { Preflight } from "@/lib/types";

/** GET /api/preflight on load, every 30 s, and on demand. `null` while the backend is unreachable. */
export function usePreflight() {
  const [data, setData] = useState<Preflight | null>(null);
  const [loading, setLoading] = useState(true);
  const [backendDown, setBackendDown] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/api/preflight`, { cache: "no-store" });
      setData(await res.json());
      setBackendDown(false);
    } catch {
      setBackendDown(true);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  return { data, loading, backendDown, refresh };
}
