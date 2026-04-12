import { LayoutList, LayoutGrid } from "lucide-react";
import type { ViewMode } from "../types";

interface Props {
  mode: ViewMode;
  onChange: (m: ViewMode) => void;
}

export default function ViewToggle({ mode, onChange }: Props) {
  return (
    <div className="flex rounded-xl bg-gray-800 p-1 gap-1">
      <button
        onClick={() => onChange("table")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
          mode === "table"
            ? "bg-indigo-600 text-white"
            : "text-gray-400 hover:text-gray-200"
        }`}
      >
        <LayoutList className="w-3.5 h-3.5" /> Table
      </button>
      <button
        onClick={() => onChange("card")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
          mode === "card"
            ? "bg-indigo-600 text-white"
            : "text-gray-400 hover:text-gray-200"
        }`}
      >
        <LayoutGrid className="w-3.5 h-3.5" /> Cards
      </button>
    </div>
  );
}
