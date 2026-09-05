import React, { useEffect, useRef } from "react";
import type { PlanItem } from "../api/types";
import { formatTimeTenths } from "../lib/format";

interface ItemListProps {
  items: PlanItem[];
  selectedItemId: string | null;
  onSelect: (id: string) => void;
  onToggleEnabled: (id: string) => void;
  errorsByItemId: Map<string, string[]>;
}

const KIND_LABEL: Record<string, string> = {
  keep: "保留",
  cut: "剪除",
  fade: "淡出",
  filler: "贅字",
  clip: "片段",
};

export const ItemList: React.FC<ItemListProps> = ({
  items,
  selectedItemId,
  onSelect,
  onToggleEnabled,
  errorsByItemId,
}) => {
  const rowRefs = useRef<Record<string, HTMLTableRowElement | null>>({});

  useEffect(() => {
    if (selectedItemId && rowRefs.current[selectedItemId]) {
      rowRefs.current[selectedItemId]?.scrollIntoView({ block: "nearest" });
    }
  }, [selectedItemId]);

  return (
    <div
      style={{
        border: "var(--border-subtle)",
        borderRadius: "var(--radius-max)",
        backgroundColor: "var(--surface-panel)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        height: "100%",
      }}
    >
      <div
        style={{
          padding: "8px 12px",
          borderBottom: "var(--border-subtle)",
          backgroundColor: "var(--surface-elevated)",
        }}
      >
        <span className="label-caps">編輯項目 (ITEMS)</span>
        <span className="kbd-hint">j/k 選取</span>
        <span className="kbd-hint">space 試聽</span>
        <span className="kbd-hint">e 切換</span>
      </div>
      <div style={{ overflowY: "auto", flex: 1 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--font-size-sm)" }}>
          <thead>
            <tr style={{ backgroundColor: "var(--surface-elevated)", height: "26px" }}>
              <th className="label-caps" style={{ padding: "0 8px", textAlign: "left" }}>
                啟用
              </th>
              <th className="label-caps" style={{ padding: "0 8px", textAlign: "left" }}>
                ID
              </th>
              <th className="label-caps" style={{ padding: "0 8px", textAlign: "left" }}>
                種類
              </th>
              <th className="label-caps mono" style={{ padding: "0 8px", textAlign: "left" }}>
                開始
              </th>
              <th className="label-caps mono" style={{ padding: "0 8px", textAlign: "left" }}>
                結束
              </th>
              <th className="label-caps" style={{ padding: "0 8px", textAlign: "left" }}>
                原因
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const selected = item.id === selectedItemId;
              const itemErrors = errorsByItemId.get(item.id);
              const hasError = Boolean(itemErrors && itemErrors.length > 0);
              return (
                <React.Fragment key={item.id}>
                  <tr
                    ref={(el) => {
                      rowRefs.current[item.id] = el;
                    }}
                    onClick={() => onSelect(item.id)}
                    style={{
                      height: "var(--row-height)",
                      cursor: "pointer",
                      backgroundColor: selected ? "var(--surface-active)" : "transparent",
                      borderLeft: hasError ? "2px solid var(--semantic-red)" : "2px solid transparent",
                    }}
                  >
                    <td style={{ padding: "0 8px" }}>
                      <input
                        type="checkbox"
                        data-testid={`item-toggle-${item.id}`}
                        checked={item.enabled}
                        onChange={(e) => {
                          e.stopPropagation();
                          onToggleEnabled(item.id);
                        }}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </td>
                    <td className="mono" style={{ padding: "0 8px", color: "var(--text-primary)" }}>
                      {item.id}
                    </td>
                    <td style={{ padding: "0 8px", color: "var(--text-muted)" }}>
                      {KIND_LABEL[item.kind] ?? item.kind}
                    </td>
                    <td className="mono tabular-nums" style={{ padding: "0 8px" }}>
                      {formatTimeTenths(item.start)}
                    </td>
                    <td className="mono tabular-nums" style={{ padding: "0 8px" }}>
                      {formatTimeTenths(item.end)}
                    </td>
                    <td
                      style={{
                        padding: "0 8px",
                        color: "var(--text-muted)",
                        fontSize: "var(--font-size-xs)",
                        maxWidth: "160px",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={item.reason}
                    >
                      {item.reason}
                    </td>
                  </tr>
                  {hasError && (
                    <tr style={{ borderLeft: "2px solid var(--semantic-red)" }}>
                      <td colSpan={6} style={{ padding: "2px 8px 6px 34px" }}>
                        {itemErrors!.map((msg, i) => (
                          <div key={i} style={{ color: "var(--semantic-red)", fontSize: "var(--font-size-xs)" }}>
                            {msg}
                          </div>
                        ))}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
