import type { ReactNode } from "react";

export function PageShell({
  eyebrow,
  title,
  intro,
  children
}: {
  eyebrow: string;
  title: string;
  intro?: string;
  children: ReactNode;
}) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1100px] px-6 py-10">
        <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-faint">{eyebrow}</p>
        <h2 className="mt-2 max-w-3xl font-serif text-2xl leading-tight text-ink md:text-3xl">{title}</h2>
        {intro && <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted">{intro}</p>}
        <div className="mt-7">{children}</div>
      </div>
    </div>
  );
}
