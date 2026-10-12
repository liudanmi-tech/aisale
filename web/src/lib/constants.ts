import type { NodeStatus, NodeType } from "@/services/api";

export const NODE_META: Record<NodeType, { label: string; ch: string; color: string }> = {
    ad: { label: "爆款", ch: "爆", color: "#ff7a45" },
    sp: { label: "卖点", ch: "卖", color: "#36cfc9" },
    aud: { label: "人群包", ch: "群", color: "#9254de" },
    script: { label: "剧本", ch: "剧", color: "#7c5cff" },
    video: { label: "视频", ch: "视", color: "#3e8bff" },
    eval: { label: "评测", ch: "评", color: "#f5a524" },
    deliver: { label: "投放", ch: "投", color: "#2bc48a" },
    data: { label: "数据", ch: "数", color: "#13c2c2" },
    opt: { label: "优化", ch: "优", color: "#eb2f96" },
};

export const STATUS_META: Record<NodeStatus | "preview", { label: string; cls: string }> = {
    none: { label: "未开始", cls: "bg-elev text-ink2" },
    run: { label: "生成中", cls: "bg-brand/20 text-[#b5a3ff]" },
    wait: { label: "待审核", cls: "bg-warn/15 text-warn" },
    pass: { label: "已通过", cls: "bg-good/15 text-good" },
    reject: { label: "已驳回", cls: "bg-bad/15 text-bad" },
    live: { label: "投放中", cls: "bg-brand2/20 text-[#8db8ff]" },
    failed: { label: "失败", cls: "bg-bad/15 text-bad" },
    preview: { label: "计划预览", cls: "bg-brand/20 text-[#b5a3ff]" },
};

export const NODE_W = 220;
export const NODE_H = 84;
/** 默认展开、内容平铺在画布上的节点类型，以及展开后的宽度（与后端 canvas.NODE_SIZE 一致） */
export const EXPANDED_W: Partial<Record<NodeType, number>> = { script: 660, video: 620, eval: 480, deliver: 400, data: 400, opt: 400 };

export const COVER_GRADIENTS = [
    "linear-gradient(160deg,#ff7a45,#7c5cff)",
    "linear-gradient(160deg,#36cfc9,#3e8bff)",
    "linear-gradient(160deg,#eb2f96,#f5a524)",
    "linear-gradient(160deg,#2bc48a,#13c2c2)",
    "linear-gradient(160deg,#9254de,#3e8bff)",
    "linear-gradient(160deg,#f25f5c,#ff7a45)",
];
