import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type ToastTone = "ok" | "danger" | "info";
interface Toast {
  id: number;
  title: string;
  message?: string;
  tone: ToastTone;
}

interface ToastApi {
  push: (title: string, opts?: { message?: string; tone?: ToastTone }) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }): ReactNode {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback<ToastApi["push"]>((title, opts) => {
    const id = Date.now() + Math.random();
    const toast: Toast = { id, title, tone: opts?.tone ?? "info", ...(opts?.message ? { message: opts.message } : {}) };
    setToasts((t) => [...t, toast]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);

  const api = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-atomic="false">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast--${t.tone}`} role="status">
            <div className="toast__title">{t.title}</div>
            {t.message && <div>{t.message}</div>}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
