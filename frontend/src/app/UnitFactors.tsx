// Units of the exports per product (Q35): «1 упак Моцареллы = 2,5 кг». The HQ admin keeps the list for the
// network; an import converts by it and never guesses. Two places: the import report (a unit the file needs)
// and «Нормы и настройки» (the whole list).
import { CheckCircle2, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useRef, useState } from "react";

import {
  useBatchAction,
  useCatalog,
  useDeleteUnitFactor,
  useSaveUnitFactor,
  useUnitFactors,
} from "../api/hooks";
import type { AffectedFiles, ImportBatch, UnitFactor, UnitFix } from "../api/types";
import { Button, ErrorText, QuestionBlock } from "../ds/primitives";
import { plural } from "../lib/format";
import { useViewer } from "../lib/useViewer";
import { useUi } from "../state/ui";

const BASE: Record<string, string> = { kg: "кг", l: "л", pcs: "шт" };

export const baseTitle = (unit: string) => BASE[unit] ?? unit;
/** "2.500000" → "2,5": a factor as people write it. */
export const showFactor = (v: string) => String(Number(v)).replace(".", ",");

function FactorInput({
  value,
  onChange,
  label,
  disabled,
  autoFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  return (
    <input
      autoFocus={autoFocus}
      inputMode="decimal"
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      aria-label={label}
      placeholder="2,5"
      className="h-9 w-24 rounded-[10px] border border-line-strong bg-surface px-2 text-right outline-none focus:border-brand"
    />
  );
}

/** One unit the file needs: «1 «упак» Сыр Моцарелла = [ ] кг». */
function FixRow({ fix, may, onSaved }: { fix: UnitFix; may: boolean; onSaved: () => void }) {
  const save = useSaveUnitFactor();
  const [value, setValue] = useState("");
  const label = `Сколько ${baseTitle(fix.base_unit)} в 1 «${fix.unit_text}» товара «${fix.product_name}»`;
  return (
    <li className="flex flex-wrap items-center gap-2">
      <span className="min-w-0 flex-1">
        1 «{fix.unit_text}» <span className="font-medium">{fix.product_name}</span>
        <span className="text-ink-3"> · {plural(fix.rows, ["строка", "строки", "строк"])}</span>
      </span>
      {save.isSuccess ? (
        <span role="status" className="inline-flex items-center gap-1 text-gain">
          <CheckCircle2 size={14} /> = {showFactor(save.data.factor.factor)} {baseTitle(fix.base_unit)}
        </span>
      ) : may ? (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(
              { product_id: fix.product_id, unit_text: fix.unit_text, factor: value.trim() },
              { onSuccess: onSaved },
            );
          }}
        >
          = <FactorInput value={value} onChange={setValue} label={label} disabled={save.isPending} />
          {baseTitle(fix.base_unit)}
          <Button type="submit" size="sm" aria-label={`Сохранить: ${label}`} disabled={save.isPending || !value.trim()}>
            Сохранить
          </Button>
        </form>
      ) : null}
      <ErrorText error={save.error} className="w-full" />
    </li>
  );
}

/** On the import report: the units the file has no factor for, set right there, then the file again. */
export function UnitFixes({ batch, onChecked }: { batch: ImportBatch; onChecked: (b: ImportBatch) => void }) {
  const viewer = useViewer();
  const recheck = useBatchAction("recheck");
  const { notify } = useUi();
  const [saved, setSaved] = useState(0);
  const fixes = batch.unit_fixes ?? [];
  if (!fixes.length || batch.status !== "failed") return null;
  const may = viewer?.can("norms.manage") ?? false;
  return (
    <div className="rounded-[14px] bg-info-soft p-4 text-sm">
      <div className="font-medium text-ink">Сколько это в базовых единицах?</div>
      <p className="mt-1 text-ink-2">
        {may
          ? "Единицы выгрузки, которых нет в справочнике. Задайте их один раз — дальше файлы с ними пойдут сами."
          : "Единицы выгрузки, которых нет в справочнике. Коэффициенты задает администратор управляющей компании: передайте ему этот список, а потом нажмите «Проверить заново»."}
      </p>
      <ul className="mt-3 space-y-2">
        {fixes.map((f) => (
          <FixRow key={`${f.product_id}:${f.unit}`} fix={f} may={may} onSaved={() => setSaved((n) => n + 1)} />
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          variant={saved >= fixes.length ? "primary" : "secondary"}
          size="sm"
          disabled={recheck.isPending}
          onClick={() =>
            recheck.mutate(batch.id, {
              onSuccess: (b) => {
                // The same errors again: say so, the screen would not change (frontend review of stage 10, p. 5).
                notify(
                  b.status === "failed"
                    ? (b.unit_fixes ?? []).length
                      ? "Проверили: у части единиц все еще нет коэффициента"
                      : "Проверили: в файле остались другие ошибки"
                    : "Файл проходит проверку — его можно загрузить",
                );
                onChecked(b);
              },
            })
          }
        >
          <RotateCcw size={14} /> Проверить заново
        </Button>
        <ErrorText error={recheck.error} />
      </div>
    </div>
  );
}

export interface Change {
  kind: "saved" | "deleted";
  files: AffectedFiles["affected_files"];
  n: number; // one more per change: the box starts afresh (frontend review of stage 10, p. 1)
}

function AffectedBox({ change }: { change: Change }) {
  const reprocess = useBatchAction("reprocess");
  const [redone, setRedone] = useState<string[]>([]);
  const files = change.files;
  if (change.kind === "deleted")
    // A file converted by a removed factor no longer passes: its rows stay as loaded (p. 2).
    return (
      <div role="status" className="mb-4 rounded-[14px] bg-info-soft p-4 text-sm text-ink-2">
        {files.length
          ? `Коэффициент удален. ${plural(files.length, ["файл, загруженный", "файла, загруженных", "файлов, загруженных"])} по нему, остаются как были; пересчитать их можно, когда коэффициент задан снова: ${files.map((f) => f.filename).join(", ")}.`
          : "Коэффициент удален. Файлов, загруженных по нему, нет."}
      </div>
    );
  return (
    <div role="status" className="mb-4 rounded-[14px] bg-info-soft p-4 text-sm">
      {files.length ? (
        <>
          <div className="font-medium text-ink">Эти файлы загружены со старым коэффициентом — пересчитайте их:</div>
          <ul className="mt-2 space-y-1.5">
            {files.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center gap-2">
                <span className="flex-1">{f.filename}</span>
                {redone.includes(f.id) ? (
                  <span className="inline-flex items-center gap-1 text-gain">
                    <CheckCircle2 size={14} /> пересчитан
                  </span>
                ) : (
                  <Button
                    size="sm"
                    aria-label={`Пересчитать файл ${f.filename}`}
                    disabled={reprocess.isPending}
                    onClick={() => reprocess.mutate(f.id, { onSuccess: () => setRedone((r) => [...r, f.id]) })}
                  >
                    <RotateCcw size={14} /> Пересчитать
                  </Button>
                )}
              </li>
            ))}
          </ul>
          <ErrorText error={reprocess.error} fallback="Не получилось пересчитать" className="mt-2" />
        </>
      ) : (
        <span className="text-ink-2">Сохранено. Файлов с этим коэффициентом нет — пересчитывать нечего.</span>
      )}
    </div>
  );
}

function FactorRow({
  factor,
  may,
  onChanged,
}: {
  factor: UnitFactor;
  may: boolean;
  onChanged: (kind: Change["kind"], files: AffectedFiles["affected_files"]) => void;
}) {
  const save = useSaveUnitFactor();
  const remove = useDeleteUnitFactor();
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [value, setValue] = useState(showFactor(factor.factor));
  const edit = useRef<HTMLButtonElement>(null);
  const base = baseTitle(factor.base_unit);
  const what = `«${factor.unit_text}» товара «${factor.product_name}»`;
  const close = () => {
    setEditing(false);
    setConfirm(false);
    setValue(showFactor(factor.factor));
    save.reset();
    remove.reset();
    requestAnimationFrame(() => edit.current?.focus());
  };
  return (
    <li className="grid gap-2 py-3 text-sm sm:grid-cols-[1fr_auto] sm:items-center">
      <span className="min-w-0">
        <span className="block font-medium">
          1 «{factor.unit_text}» {factor.product_name}
          {!editing && (
            <span className="num font-normal">
              {" "}
              = {showFactor(factor.factor)} {base}
            </span>
          )}
        </span>
        <span className="block text-xs text-ink-3">
          {factor.files ? plural(factor.files, ["файл", "файла", "файлов"]) : "файлов пока нет"}
        </span>
      </span>
      {may ? (
        <span className="flex flex-wrap items-center gap-1 sm:justify-end">
          {editing ? (
            <form
              className="flex flex-wrap items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate(
                  { product_id: factor.product_id, unit_text: factor.unit_text, factor: value.trim() },
                  {
                    onSuccess: (r) => {
                      setEditing(false);
                      onChanged("saved", r.affected_files);
                    },
                  },
                );
              }}
            >
              ={" "}
              <FactorInput
                autoFocus
                value={value}
                onChange={setValue}
                label={`Сколько ${base} в 1 «${factor.unit_text}» товара «${factor.product_name}»`}
              />
              {base}
              <Button type="submit" size="sm" aria-label={`Сохранить коэффициент ${what}`} disabled={save.isPending || !value.trim()}>
                Сохранить
              </Button>
              <Button size="sm" variant="ghost" onClick={close}>
                Отмена
              </Button>
            </form>
          ) : confirm ? (
            <>
              <Button
                size="sm"
                variant="danger"
                autoFocus
                aria-label={`Удалить коэффициент ${what}`}
                disabled={remove.isPending}
                onClick={() => remove.mutate(factor.id, { onSuccess: (r) => onChanged("deleted", r.affected_files) })}
              >
                Удалить
              </Button>
              <Button size="sm" variant="ghost" aria-label={`Не удалять коэффициент ${what}`} onClick={close}>
                Не надо
              </Button>
            </>
          ) : (
            <>
              <Button ref={edit} size="sm" variant="ghost" aria-label={`Исправить коэффициент ${what}`} onClick={() => setEditing(true)}>
                Исправить
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirm(true)} aria-label={`Удалить коэффициент ${what}`}>
                <Trash2 size={14} />
              </Button>
            </>
          )}
        </span>
      ) : null}
      <ErrorText error={save.error ?? remove.error} className="sm:col-span-2" />
    </li>
  );
}

function AddFactor({ onSaved }: { onSaved: () => void }) {
  const products = useCatalog("product");
  const save = useSaveUnitFactor();
  const [product, setProduct] = useState("");
  const [unit, setUnit] = useState("");
  const [value, setValue] = useState("");
  const base = products.data?.find((p) => p.id === product)?.base_unit;
  const howMuch = base ? `Сколько ${baseTitle(base)} в ней` : "Сколько базовых единиц в ней";
  return (
    <form
      className="mt-3 flex flex-wrap items-end gap-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(
          { product_id: product, unit_text: unit.trim(), factor: value.trim() },
          {
            onSuccess: () => {
              setUnit("");
              setValue("");
              onSaved();
            },
          },
        );
      }}
    >
      <label className="flex flex-col gap-1">
        Товар
        <select
          value={product}
          onChange={(e) => setProduct(e.target.value)}
          className="h-9 max-w-[16rem] rounded-[10px] border border-line-strong bg-surface px-2 outline-none focus:border-brand"
        >
          <option value="">Выберите товар</option>
          {(products.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        Единица в выгрузке
        <input
          value={unit}
          maxLength={40}
          onChange={(e) => setUnit(e.target.value)}
          placeholder="упак"
          className="h-9 w-28 rounded-[10px] border border-line-strong bg-surface px-2 outline-none focus:border-brand"
        />
      </label>
      <label className="flex flex-col gap-1">
        {howMuch}
        <FactorInput value={value} onChange={setValue} label={howMuch} />
      </label>
      <Button type="submit" size="sm" disabled={save.isPending || !product || !unit.trim() || !value.trim()}>
        <Plus size={14} /> Добавить
      </Button>
      <ErrorText error={save.error} className="w-full" />
    </form>
  );
}

/** «Нормы и настройки»: the network's list of units. */
export function UnitFactorsSection() {
  const viewer = useViewer();
  const { data: factors = [], isError } = useUnitFactors();
  const [change, setChange] = useState<Change | null>(null);
  const may = viewer?.can("norms.manage") ?? false;
  return (
    <QuestionBlock
      question="Единицы в выгрузках"
      answer={
        factors.length
          ? `${plural(factors.length, ["коэффициент", "коэффициента", "коэффициентов"])}: сколько базовых единиц товара в упаковке, бутылке, коробке из выгрузки. Кг, г, л, мл и шт переводятся сами.`
          : "Кг, г, л, мл и шт переводятся сами. Если поставщик пишет «упак» или «бут», задайте здесь, сколько это в базовых единицах товара — или прямо в отчете о загрузке."
      }
    >
      {isError && <p className="text-sm text-loss">Не получилось загрузить список — обновите страницу</p>}
      {change && <AffectedBox key={change.n} change={change} />}
      {factors.length > 0 && (
        <ul className="divide-y divide-line">
          {factors.map((f) => (
            <FactorRow
              key={f.id}
              factor={f}
              may={may}
              onChanged={(kind, files) => setChange((c) => ({ kind, files, n: (c?.n ?? 0) + 1 }))}
            />
          ))}
        </ul>
      )}
      {may ? (
        <AddFactor onSaved={() => setChange(null)} />
      ) : (
        <p className="mt-2 text-sm text-ink-3">Коэффициенты задает администратор управляющей компании.</p>
      )}
    </QuestionBlock>
  );
}
