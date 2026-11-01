import clsx from "clsx";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { EmptyState, ErrorState, LoadingState } from "./states";

export interface Column<T> {
  /** unique within the table */
  key: string;
  header: ReactNode;
  /** cell content */
  cell: (row: T) => ReactNode;
  /** When set the header is clickable and rows sort by this value (client side). */
  sortValue?: (row: T) => string | number | null | undefined;
  align?: "left" | "right" | "center";
  /** CSS width, e.g. "8rem" */
  width?: string;
  className?: string;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  /** undefined while nothing has loaded yet */
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** show the loading state (first load); the rows stay visible during background refetches */
  isLoading?: boolean;
  /** show the error state instead of rows */
  error?: unknown;
  onRetry?: () => void;
  emptyTitle?: string;
  emptyHint?: ReactNode;
  emptyAction?: ReactNode;
  /** highlights the row with this key (e.g. the one open in a drawer) */
  selectedKey?: string | null;
  rowClassName?: (row: T) => string | undefined;
  initialSort?: { key: string; dir: "asc" | "desc" };
  caption?: string;
  className?: string;
}

function compare(a: string | number | null | undefined, b: string | number | null | undefined): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1; // empty values last
  if (b === null || b === undefined) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/**
 * Generic table with the three states every page needs: loading (skeleton), error (with retry) and empty.
 * Columns with `sortValue` sort on header click. Rows are keyboard-activatable when `onRowClick` is set.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  isLoading,
  error,
  onRetry,
  emptyTitle = "Nothing here yet",
  emptyHint,
  emptyAction,
  selectedKey,
  rowClassName,
  initialSort,
  caption,
  className,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" } | null>(initialSort ?? null);

  const sorted = useMemo(() => {
    if (!rows) return rows;
    const column = sort ? columns.find((c) => c.key === sort.key) : undefined;
    if (!sort || !column?.sortValue) return rows;
    const get = column.sortValue;
    const factor = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => factor * compare(get(a), get(b)));
  }, [rows, sort, columns]);

  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (isLoading && !rows) return <LoadingState variant="skeleton" />;
  if (rows && rows.length === 0) return <EmptyState title={emptyTitle} hint={emptyHint} action={emptyAction} />;

  const toggleSort = (column: Column<T>) => {
    if (!column.sortValue) return;
    setSort((prev) =>
      prev?.key === column.key ? { key: column.key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key: column.key, dir: "asc" },
    );
  };

  return (
    <div className={clsx("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-left text-sm">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => {
              const active = sort?.key === column.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  className={clsx("th", column.align === "right" && "text-right", column.align === "center" && "text-center")}
                  style={column.width ? { width: column.width } : undefined}
                  aria-sort={active ? (sort?.dir === "asc" ? "ascending" : "descending") : undefined}
                >
                  {column.sortValue ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-ink"
                      onClick={() => toggleSort(column)}
                    >
                      {column.header}
                      {active ? sort?.dir === "asc" ? <ChevronUp size={12} /> : <ChevronDown size={12} /> : null}
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {(sorted ?? []).map((row) => {
            const key = rowKey(row);
            return (
              <tr
                key={key}
                data-row-key={key}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
                aria-selected={selectedKey === key ? true : undefined}
                className={clsx(
                  onRowClick && "cursor-pointer hover:bg-bg",
                  selectedKey === key && "bg-[#EFE6DC]",
                  rowClassName?.(row),
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={clsx(
                      "td",
                      column.align === "right" && "text-right",
                      column.align === "center" && "text-center",
                      column.className,
                    )}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
