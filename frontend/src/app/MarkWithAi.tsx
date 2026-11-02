import { Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useAppContext, useConfirmMarking, useMarkFile } from "../api/hooks";
import { AiBadge } from "../ds/ai";
import { Button, ErrorText } from "../ds/primitives";
import { plural } from "../lib/format";
import { useViewer } from "../lib/useViewer";

/**
 * A file the import did not understand: the assistant marks which column is which, the import checks the
 * marking on the file, the person confirms it once — then this export loads by itself (ADR 0008).
 */
export function MarkWithAi({
  file,
  restaurantId,
  templates,
  template: chosen,
  onConfirmed,
}: {
  file: File;
  restaurantId: string | null;
  templates: { name: string; title: string }[];
  template: string | null;
  onConfirmed: () => void;
}) {
  const context = useAppContext();
  const viewer = useViewer();
  const mark = useMarkFile();
  const confirm = useConfirmMarking();
  const [template, setTemplate] = useState(chosen ?? templates[0]?.name ?? "");
  // The button goes away with the result: focus moves to the result, not to the page (review 02.11, front p. 9).
  const resultRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (mark.data) resultRef.current?.focus();
  }, [mark.data]);
  if (!context.data?.assistant) return null;
  const m = mark.data;

  return (
    <section aria-label="Разметка файла с ИИ" className="rounded-[14px] border border-dashed border-line-strong p-4 text-sm">
      {!m ? (
        <>
          <div className="font-medium">Незнакомый формат файла</div>
          <p className="mt-1 text-ink-2">
            ИИ подскажет, какая колонка что значит. Разметку проверим на этом файле, а вы подтвердите ее один раз:{" "}
            {viewer?.isHq ? "дальше такие файлы будут загружаться сами во всей сети" : "дальше такие файлы вашего ресторана будут загружаться сами"}.
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            {!chosen && (
              <label>
                <span className="mb-1 block text-ink-3">Что в файле</span>
                <select
                  value={template}
                  onChange={(e) => setTemplate(e.target.value)}
                  className="h-9 rounded-[10px] border border-line-strong bg-surface px-3"
                >
                  {templates.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.title}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <Button size="sm" variant="primary" disabled={mark.isPending || !template} onClick={() => mark.mutate({ file, restaurantId, template })}>
              <Sparkles size={14} aria-hidden /> {mark.isPending ? "Размечаю…" : "Разметить с ИИ"}
            </Button>
          </div>
        </>
      ) : (
        <>
          <h3 ref={resultRef} tabIndex={-1} className="flex items-center gap-2 font-medium outline-none">
            Разметка ИИ <AiBadge basis="По заголовкам и первым строкам файла. Разметку уже проверил импорт на этом файле." />
          </h3>
          <table className="mt-2 w-full text-left">
            <thead className="text-ink-3">
              <tr>
                <th className="py-1 pr-3 font-medium">Поле</th>
                <th className="py-1 pr-3 font-medium">Колонка файла</th>
                <th className="py-1 font-medium">Почему</th>
              </tr>
            </thead>
            <tbody>
              {m.columns.map((c) => (
                <tr key={c.field} className="border-t border-line">
                  <td className="py-1 pr-3">{c.title}</td>
                  <td className="py-1 pr-3 font-medium">{c.header}</td>
                  <td className="py-1 text-ink-3">{c.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-ink-2">
            С этой разметкой: {plural(Number(m.preview.rows ?? 0), ["строка", "строки", "строк"])}, с ошибками —{" "}
            {Number(m.preview.rows_with_errors ?? 0)}.
          </p>
          <Button className="mt-3" size="sm" variant="primary" disabled={confirm.isPending} onClick={() => confirm.mutate(m.id, { onSuccess: onConfirmed })}>
            Подтвердить и загрузить
          </Button>
        </>
      )}
      <ErrorText error={mark.error ?? confirm.error} className="mt-2" />
    </section>
  );
}
