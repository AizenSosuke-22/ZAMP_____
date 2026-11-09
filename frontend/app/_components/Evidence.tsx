import { labelFor, money, num } from "../_lib/format";

const MONEY_KEY = /total|amount|price|value|balance|tolerance|variance$|^grand/i;
const HIDDEN = new Set(["earlier_cases_checked"]);

function fmt(key: string, v: unknown): React.ReactNode {
  if (v == null || v === "") return <span className="text-ink-3">—</span>;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") {
    if (/pct|percent/i.test(key)) return <span className="num">{num(v)}%</span>;
    if (MONEY_KEY.test(key)) return <span className="num">{money(v)}</span>;
    return <span className="num">{num(v)}</span>;
  }
  if (typeof v === "string") return /^(CASE-|PO-)|\d{2}[A-Z]{5}\d{4}/.test(v) ? <span className="num">{v}</span> : v;
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ");
  return null;
}

/** Renders an op's evidence dict: scalars as a definition list, arrays of rows as a compact table. */
export function Evidence({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(([k]) => !HIDDEN.has(k));
  const scalars = entries.filter(([, v]) => !(Array.isArray(v) && v.some((x) => typeof x === "object")) && !(v && typeof v === "object" && !Array.isArray(v)));
  const tables = entries.filter(([, v]) => Array.isArray(v) && v.some((x) => typeof x === "object")) as [string, Record<string, unknown>[]][];
  const nested = entries.filter(([, v]) => v && typeof v === "object" && !Array.isArray(v)) as [string, Record<string, unknown>][];
  if (!entries.length) return null;

  return (
    <div className="space-y-3 text-[13px]">
      {scalars.length > 0 && (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
          {scalars.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-ink-3">{labelFor(k)}</dt>
              <dd className="text-ink-2">{fmt(k, v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {nested.map(([k, v]) => (
        <div key={k}>
          <p className="mb-1 text-ink-3">{labelFor(k)}</p>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 pl-3">
            {Object.entries(v).map(([k2, v2]) => (
              <div key={k2} className="contents">
                <dt className="num text-ink-3">{k2}</dt>
                <dd className="text-ink-2">{fmt(k, v2)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
      {tables.map(([k, rows]) => {
        const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r))));
        return (
          <div key={k} className="overflow-x-auto rounded-md border border-line">
            <table className="w-full text-left text-[12px]">
              <thead className="bg-sunk text-ink-3">
                <tr>
                  {cols.map((c) => (
                    <th key={c} className="px-2.5 py-1.5 font-medium whitespace-nowrap">
                      {labelFor(c)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className={`border-t border-line ${r.ok === false ? "bg-bad-bg/60" : ""}`}>
                    {cols.map((c) => (
                      <td key={c} className={`px-2.5 py-1.5 align-top text-ink-2 ${c === "desc" ? "min-w-48" : "whitespace-nowrap"}`}>
                        {fmt(c, r[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
