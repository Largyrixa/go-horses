import { STATUS } from "@/utils/format";

export function PageTitle({ children }) {
  return (
    <h1 className="glitch-hover mb-8 font-display text-4xl text-white md:text-5xl">
      {children}<span className="text-primary motion-safe:animate-pulse">_</span>
    </h1>
  );
}

export function StatusBadge({ status }) {
  const s = STATUS[status] || { label: status, cls: "border-gray text-gray" };
  return <span className={`inline-block rounded border px-2.5 py-0.5 font-mono text-xs ${s.cls}`}>{s.label}</span>;
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-base text-textColor">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-sm text-gray">{hint}</span>}
    </label>
  );
}

export function ErrorNote({ children }) {
  if (!children) return null;
  return <p role="alert" className="rounded-md border border-danger/60 bg-danger/10 px-4 py-3 text-base text-danger">{children}</p>;
}

export function Empty({ children, action }) {
  return (
    <div className="rounded-lg border border-dashed border-edge px-6 py-14 text-center text-gray">
      <p className="mb-5">{children}</p>
      {action}
    </div>
  );
}
