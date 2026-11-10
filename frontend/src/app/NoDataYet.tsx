import { Link } from "@tanstack/react-router";
import { UploadCloud } from "lucide-react";

import { useAppContext } from "../api/hooks";
import { buttonClass, EmptyState } from "../ds/primitives";

/**
 * A network that has not loaded anything yet (docs/10 §5 «Нет данных»): say so and lead to «Данные», instead of
 * zeros and «Проблем выше нормы нет» (pre-pilot review 10.11.2026, p. 6). Null while there is data.
 */
export function NoDataYet({ canUpload }: { canUpload: boolean }) {
  const context = useAppContext();
  if (!context.data || context.data.data_until !== null) return null;
  return (
    <EmptyState
      title="Данных пока нет"
      action={
        canUpload && (
          <Link to="/data" className={buttonClass("primary")}>
            <UploadCloud size={16} /> Загрузить данные
          </Link>
        )
      }
    >
      {canUpload
        ? "Цифры появятся после первых выгрузок: сначала справочники сети (рестораны, номенклатура, поставщики, блюда, техкарты), затем продажи, приходы и списания ресторанов."
        : "Управляющая компания еще не загрузила данные ресторана — цифры появятся после первой выгрузки."}
    </EmptyState>
  );
}

/** True when the network has no data at all yet (the screens then show `NoDataYet` alone). */
export function useNoData(): boolean {
  const context = useAppContext();
  return context.data?.data_until === null;
}
