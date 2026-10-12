import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

/** 画布节点的收起状态：默认展开，用户收起的节点 id 记在本机，刷新后保持。 */
export const useCollapseStore = create<{ collapsed: Record<string, true>; setCollapsed: (id: string, v: boolean) => void }>()(
    persist(
        (set) => ({
            collapsed: {},
            setCollapsed: (id, v) => set((s) => {
                const next = { ...s.collapsed };
                if (v) next[id] = true;
                else delete next[id];
                return { collapsed: next };
            }),
        }),
        {
            name: "aigc-canvas-collapsed",
            storage: createJSONStorage(() => {
                try {
                    return localStorage;
                } catch {
                    return sessionStorage;
                }
            }),
        },
    ),
);
