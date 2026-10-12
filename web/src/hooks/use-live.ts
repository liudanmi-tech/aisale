import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

const KEYS: Record<string, string[][]> = {
    canvas: [["canvas"], ["flow"], ["node"], ["delivery"], ["optimizations"], ["metrics"]],
    chat: [["chat"]],
    reviews: [["reviews"], ["dashboard"], ["flow"], ["node"], ["delivery"], ["optimizations"]],
    delivery: [["delivery"]],
};

/** 订阅项目实时事件（WebSocket），按事件类型刷新对应数据。 */
export function useLive(projectId: string) {
    const qc = useQueryClient();
    useEffect(() => {
        let ws: WebSocket | null = null;
        let stop = false;
        let retry: ReturnType<typeof setTimeout>;
        const connect = () => {
            const proto = location.protocol === "https:" ? "wss" : "ws";
            ws = new WebSocket(`${proto}://${location.host}/api/v1/projects/${projectId}/live`);
            ws.onmessage = (e) => {
                const evt = JSON.parse(e.data) as { type: string };
                (KEYS[evt.type] || []).forEach((k) => qc.invalidateQueries({ queryKey: k }));
            };
            ws.onclose = () => {
                if (!stop) retry = setTimeout(connect, 2000);
            };
        };
        connect();
        return () => {
            stop = true;
            clearTimeout(retry);
            ws?.close();
        };
    }, [projectId, qc]);
}
