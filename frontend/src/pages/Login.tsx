import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";

import { ApiError, login } from "../api/client";
import { PRODUCT_NAME } from "../config";

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login(email, password);
      queryClient.clear();
      await navigate({ to: "/" });
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? "Неверный email или пароль" : "Ошибка входа");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 rounded-xl bg-white p-8 shadow">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">{PRODUCT_NAME}</h1>
          <p className="text-sm text-slate-500">Вход в систему</p>
        </div>
        <label className="block">
          <span className="text-sm text-slate-700">Email</span>
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="block">
          <span className="text-sm text-slate-700">Пароль</span>
          <input
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-md bg-slate-900 py-2 font-medium text-white disabled:opacity-50"
        >
          {pending ? "Входим…" : "Войти"}
        </button>
        <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-600">
          Демо-доступ, пароль <span className="font-mono">demo12345</span>:
          <div className="mt-1 flex flex-wrap gap-1.5">
            {[
              ["admin@demo.local", "Управляющая компания"],
              ["director1@demo.local", "Директор ресторана"],
            ].map(([demoEmail, label]) => (
              <button
                key={demoEmail}
                type="button"
                className="rounded border border-slate-300 bg-white px-2 py-1 hover:bg-slate-100"
                onClick={() => {
                  setEmail(demoEmail!);
                  setPassword("demo12345");
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </form>
    </div>
  );
}
