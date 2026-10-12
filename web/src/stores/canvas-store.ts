import { create } from "zustand";

interface View {
    x: number;
    y: number;
    z: number;
}

interface CanvasState {
    view: View;
    selection: string[];
    highlight: string[];
    focusRequest: { id: string; ts: number } | null;
    setView: (v: View) => void;
    select: (ids: string[]) => void;
    toggle: (id: string) => void;
    setHighlight: (ids: string[]) => void;
    focus: (id: string) => void;
}

export const useCanvasStore = create<CanvasState>((set) => ({
    view: { x: 40, y: 40, z: 1 },
    selection: [],
    highlight: [],
    focusRequest: null,
    setView: (view) => set({ view }),
    select: (selection) => set({ selection }),
    toggle: (id) => set((s) => ({ selection: s.selection.includes(id) ? s.selection.filter((x) => x !== id) : [...s.selection, id] })),
    setHighlight: (highlight) => set({ highlight }),
    focus: (id) => set({ focusRequest: { id, ts: Date.now() }, selection: [id] }),
}));
