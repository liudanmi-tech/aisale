import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

/** 当前项目：投放中心、数据看板等按项目展示的页面都跟随它；进入某个项目画布时自动切换。 */
export const useProjectStore = create<{ pid: string; setPid: (pid: string) => void }>()(
    persist((set) => ({ pid: "p1", setPid: (pid) => set({ pid }) }), {
        name: "aigc-current-project",
        storage: createJSONStorage(() => {
            try {
                return localStorage;
            } catch {
                return sessionStorage;
            }
        }),
    }),
);

export const useCurrentProject = () => useProjectStore((s) => s.pid);
