import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";

import { changePassword } from "../api/client";
import { useMe } from "../api/hooks";
import { Button, Card, ErrorText } from "../ds/primitives";

const MIN = 10;

/**
 * What is wrong with the new password before it is sent, in the order the person fixes it; null — send it. Length
 * in characters as the server counts them (code points: an emoji is one), not in UTF-16 units.
 */
export function passwordProblem(current: string, fresh: string, repeat: string): string | null {
  if (Array.from(fresh).length < MIN) return `Новый пароль — не короче ${MIN} символов`;
  if (fresh !== repeat) return "Пароли не совпадают";
  if (fresh === current) return "Новый пароль должен отличаться от текущего";
  return null;
}

const INPUT =
  "mt-1.5 h-11 w-full rounded-[10px] border border-line-strong bg-surface px-3 outline-none focus:border-brand";

/**
 * The person's own password (docs/09 «Учетные записи»). A password handed out by the operator is changed here
 * before anything else; the other sign-ins of the person end, this one goes on.
 */
export function PasswordPage() {
  const { data: me } = useMe();
  const { next } = useSearch({ from: "/app/password" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState("");
  const [fresh, setFresh] = useState("");
  const [repeat, setRepeat] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);
  const required = me?.must_change_password === true;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const found = passwordProblem(current, fresh, repeat);
    setProblem(found);
    if (found) return;
    setPending(true);
    try {
      await changePassword(current, fresh);
      await queryClient.invalidateQueries();
      setCurrent("");
      setFresh("");
      setRepeat("");
      if (required) await navigate({ href: next ?? "/" });
      else setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <h1 className="font-display text-2xl font-semibold">{required ? "Задайте свой пароль" : "Смена пароля"}</h1>
      <p className="mt-1 text-sm text-ink-3">
        {required
          ? "Пароль выдал администратор. Чтобы продолжить, придумайте свой — его будете знать только вы."
          : "После смены вход на других устройствах закончится."}
      </p>
      <Card className="mt-5 p-5">
        <form onSubmit={(e) => void onSubmit(e)} className="space-y-4">
          <label className="block">
            <span className="text-sm font-medium">{required ? "Выданный пароль" : "Текущий пароль"}</span>
            <input
              className={INPUT}
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Новый пароль</span>
            <input
              className={INPUT}
              type="password"
              autoComplete="new-password"
              value={fresh}
              onChange={(e) => setFresh(e.target.value)}
              aria-describedby="new-password-hint"
              required
            />
          </label>
          <p id="new-password-hint" className="-mt-3 text-xs text-ink-3">
            Не короче {MIN} символов
          </p>
          <label className="block">
            <span className="text-sm font-medium">Повторите новый пароль</span>
            <input
              className={INPUT}
              type="password"
              autoComplete="new-password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              required
            />
          </label>
          {problem && <p className="text-sm text-loss">{problem}</p>}
          {error !== null && <ErrorText error={error} />}
          {done && <p className="text-sm text-gain">Пароль изменен</p>}
          <Button type="submit" variant="primary" className="w-full" disabled={pending}>
            {pending ? "Сохраняем…" : "Сменить пароль"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
