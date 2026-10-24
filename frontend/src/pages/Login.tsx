import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { motion } from "motion/react";
import { type FormEvent, useState } from "react";

import { ApiError, login } from "../api/client";
import { Logo } from "../brand/Logo";
import { Button, EASE } from "../ds/primitives";

const DEMO = [
  { email: "admin@demo.local", label: "Управляющая компания", hint: "вся сеть" },
  { email: "director1@demo.local", label: "Директор ресторана", hint: "Тверская" },
];

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function signIn(e: string, p: string) {
    setPending(true);
    setError(null);
    try {
      await login(e, p);
      queryClient.clear();
      await navigate({ to: "/" });
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Неверный email или пароль" : "Не получилось войти, попробуйте еще раз");
    } finally {
      setPending(false);
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void signIn(email, password);
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-ink p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <Logo />
        <div>
          <motion.h1
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: EASE }}
            className="max-w-md font-display text-[40px] leading-[1.1] font-semibold"
          >
            Су-шеф, который находит, где ресторан теряет деньги
          </motion.h1>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3, duration: 0.6 }}
            className="mt-4 max-w-md text-white/70"
          >
            Каждую неделю: потенциал прибыли, три главных дела и проверка, что изменения сработали.
          </motion.p>
        </div>
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, duration: 0.6, ease: EASE }}
          className="max-w-sm rounded-[20px] bg-white/[0.07] p-5"
        >
          <div className="text-sm text-spark">Потенциал прибыли</div>
          <div className="font-display text-4xl font-semibold">128 тыс ₽</div>
          <div className="text-sm text-white/60">в месяц · пример ресторана из демо-сети</div>
        </motion.div>
      </div>
      <div className="flex items-center justify-center bg-paper px-4 py-12">
        <form onSubmit={onSubmit} className="w-full max-w-sm space-y-5">
          <div className="lg:hidden">
            <Logo />
          </div>
          <div>
            <h2 className="font-display text-2xl font-semibold">Вход</h2>
            <p className="mt-1 text-sm text-ink-3">Прототип на демонстрационных данных</p>
          </div>
          <label className="block">
            <span className="text-sm font-medium">Email</span>
            <input
              className="mt-1.5 h-11 w-full rounded-[10px] border border-line-strong bg-surface px-3 outline-none focus:border-brand"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Пароль</span>
            <input
              className="mt-1.5 h-11 w-full rounded-[10px] border border-line-strong bg-surface px-3 outline-none focus:border-brand"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && <p className="text-sm text-loss">{error}</p>}
          <Button type="submit" variant="primary" size="lg" className="w-full" disabled={pending}>
            {pending ? "Входим…" : "Войти"}
          </Button>
          <div className="rounded-[16px] border border-line bg-surface p-4">
            <div className="text-sm font-medium">Посмотреть демо</div>
            <div className="mt-3 grid gap-2">
              {DEMO.map((d) => (
                <button
                  key={d.email}
                  type="button"
                  disabled={pending}
                  onClick={() => {
                    setEmail(d.email);
                    setPassword("demo12345");
                    void signIn(d.email, "demo12345");
                  }}
                  className="flex items-center justify-between rounded-[12px] border border-line-strong px-4 py-3 text-left transition hover:border-brand hover:bg-brand-soft"
                >
                  <span className="font-medium">{d.label}</span>
                  <span className="text-xs text-ink-3">{d.hint} →</span>
                </button>
              ))}
            </div>
            <div className="mt-3 text-xs text-ink-3">
              Или вручную: логины admin@demo.local, director1@demo.local … director3@demo.local, пароль demo12345
            </div>
          </div>
          <Link to="/design" className="block text-center text-sm text-brand-strong hover:underline">
            Бренд и дизайн-система →
          </Link>
        </form>
      </div>
    </div>
  );
}
