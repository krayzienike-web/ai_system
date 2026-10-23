import type { Section } from "../sections";

export function PlaceholderPage({ section }: { section: Section }) {
  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-2xl font-semibold">{section.title}</h1>
      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6">
        <p>{section.description}</p>
        <p className="mt-2 text-sm text-slate-500">Раздел появится: {section.stage}.</p>
      </div>
    </div>
  );
}
