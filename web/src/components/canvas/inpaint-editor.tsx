import { useMutation } from "@tanstack/react-query";
import { App, Checkbox, Input, Modal, Segmented, Slider } from "antd";
import { Brush, Eraser, Paintbrush, RotateCcw, Trash2, Undo2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "@/services/api";

const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";
type Engine = "auto" | "flux" | "gemini";

/** 关键帧局部重绘：在图上涂出要改的地方，写一句改成什么。遮罩外的像素保持原样。 */
export function InpaintButton({ nid, i, keyframe, hasProduct, history, disabled, onDone }:
    { nid: string; i: number; keyframe: string; hasProduct: boolean; history: number; disabled: boolean; onDone: () => void }) {
    const { message } = App.useApp();
    const [open, setOpen] = useState(false);
    const undo = useMutation({
        mutationFn: () => api.undoKeyframe(nid, i),
        onSuccess: () => { message.success("已撤回到上一版关键帧"); onDone(); },
        onError: (e) => message.error(errMsg(e)),
    });
    return (
        <>
            <button data-ui disabled={disabled} onClick={() => setOpen(true)}
                className="flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-line bg-transparent px-2 py-0.5 text-[11px] text-ink hover:border-[#4a4a52] disabled:cursor-default disabled:opacity-50">
                <Paintbrush size={10} />局部重绘
            </button>
            {history > 0 && (
                <button data-ui disabled={disabled || undo.isPending} onClick={() => undo.mutate()} title="撤回上一次局部重绘"
                    className="flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border border-line bg-transparent px-2 py-0.5 text-[11px] text-ink hover:border-[#4a4a52] disabled:cursor-default disabled:opacity-50">
                    <Undo2 size={10} />撤回重绘
                </button>
            )}
            {open && <InpaintModal nid={nid} i={i} keyframe={keyframe} hasProduct={hasProduct} onClose={() => setOpen(false)} onDone={onDone} />}
        </>
    );
}

function InpaintModal({ nid, i, keyframe, hasProduct, onClose, onDone }:
    { nid: string; i: number; keyframe: string; hasProduct: boolean; onClose: () => void; onDone: () => void }) {
    const { message } = App.useApp();
    const cv = useRef<HTMLCanvasElement>(null);
    const [size, setSize] = useState<[number, number] | null>(null);
    const [brush, setBrush] = useState(40);
    const [erase, setErase] = useState(false);
    const [prompt, setPrompt] = useState("");
    const [engine, setEngine] = useState<Engine>("auto");
    const [product, setProduct] = useState(false);
    const [painted, setPainted] = useState(false);
    const stack = useRef<ImageData[]>([]);
    const drawing = useRef<{ x: number; y: number } | null>(null);

    useEffect(() => {  // 遮罩画布按关键帧原图尺寸
        const img = new Image();
        img.onload = () => setSize([img.naturalWidth, img.naturalHeight]);
        img.src = keyframe;
    }, [keyframe]);

    const pos = (e: React.PointerEvent) => {
        const c = cv.current!, r = c.getBoundingClientRect();
        return { x: ((e.clientX - r.left) / r.width) * c.width, y: ((e.clientY - r.top) / r.height) * c.height };
    };
    const line = (a: { x: number; y: number }, b: { x: number; y: number }) => {
        const ctx = cv.current!.getContext("2d")!;
        ctx.globalCompositeOperation = erase ? "destination-out" : "source-over";
        ctx.strokeStyle = "rgb(255,60,60)";
        ctx.lineWidth = brush * (cv.current!.width / 360);
        ctx.lineCap = ctx.lineJoin = "round";
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
    };
    const down = (e: React.PointerEvent) => {
        const c = cv.current!;
        stack.current.push(c.getContext("2d")!.getImageData(0, 0, c.width, c.height));
        if (stack.current.length > 30) stack.current.shift();
        c.setPointerCapture(e.pointerId);
        drawing.current = pos(e);
        line(drawing.current, drawing.current);
        if (!erase) setPainted(true);
    };
    const move = (e: React.PointerEvent) => {
        if (!drawing.current) return;
        const p = pos(e);
        line(drawing.current, p);
        drawing.current = p;
    };
    const up = () => { drawing.current = null; };
    const undoStroke = () => {
        const last = stack.current.pop();
        if (last) cv.current!.getContext("2d")!.putImageData(last, 0, 0);
    };
    const clear = () => {
        const c = cv.current!;
        stack.current.push(c.getContext("2d")!.getImageData(0, 0, c.width, c.height));
        c.getContext("2d")!.clearRect(0, 0, c.width, c.height);
        setPainted(false);
    };

    const go = useMutation({
        mutationFn: () => api.inpaintKeyframe(nid, i, { mask: cv.current!.toDataURL("image/png"), prompt: prompt.trim(), engine, product }),
        onSuccess: () => { message.info(`镜 ${i + 1} 局部重绘中，画好后停下等你确认`); onDone(); onClose(); },
        onError: (e) => message.error(errMsg(e)),
    });
    const w = 360, h = size ? Math.round((w * size[1]) / size[0]) : 640;

    return (
        <Modal open onCancel={onClose} width={760} title={`镜 ${i + 1} · 局部重绘关键帧`} okText="重绘涂过的地方" cancelText="取消"
            okButtonProps={{ disabled: !painted || !prompt.trim(), loading: go.isPending }} onOk={() => go.mutate()}>
            <div className="flex gap-4 max-[700px]:flex-col">
                <div className="relative shrink-0 overflow-hidden rounded-lg bg-black" style={{ width: w, height: h }}>
                    <img src={keyframe} alt="" draggable={false} className="absolute inset-0 h-full w-full select-none object-contain" />
                    {size && (
                        <canvas ref={cv} width={size[0]} height={size[1]} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={up}
                            className="absolute inset-0 h-full w-full touch-none opacity-50" style={{ cursor: erase ? "cell" : "crosshair" }} />
                    )}
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-3 text-[13px]">
                    <div className="text-ink2">在图上涂出要重画的地方（红色），没涂的地方保持原样、一个像素都不变。</div>
                    <div className="flex flex-wrap items-center gap-2">
                        <Segmented size="small" value={erase ? "erase" : "brush"} onChange={(v) => setErase(v === "erase")}
                            options={[{ value: "brush", label: <span className="flex items-center gap-1"><Brush size={12} />画笔</span> },
                                { value: "erase", label: <span className="flex items-center gap-1"><Eraser size={12} />橡皮</span> }]} />
                        <button className="flex cursor-pointer items-center gap-1 rounded border border-line bg-transparent px-2 py-0.5 text-[12px] text-ink" onClick={undoStroke}><RotateCcw size={12} />撤一笔</button>
                        <button className="flex cursor-pointer items-center gap-1 rounded border border-line bg-transparent px-2 py-0.5 text-[12px] text-ink" onClick={clear}><Trash2 size={12} />清空</button>
                    </div>
                    <div className="flex items-center gap-2"><span className="shrink-0 text-ink2">笔刷</span><Slider className="flex-1" min={8} max={120} value={brush} onChange={setBrush} /></div>
                    <div>
                        <div className="mb-1 text-ink2">涂的地方改成什么</div>
                        <Input.TextArea autoSize={{ minRows: 3, maxRows: 6 }} value={prompt} onChange={(e) => setPrompt(e.target.value)}
                            placeholder="如：她手里的手机换成屏幕朝镜头；把背后的铲车改成正面；去掉左边多出来的人" />
                    </div>
                    <div>
                        <div className="mb-1 text-ink2">重绘方式</div>
                        <Segmented size="small" value={engine} onChange={(v) => setEngine(v as Engine)} options={[
                            { value: "auto", label: "自动" }, { value: "flux", label: "FLUX Fill" }, { value: "gemini", label: "Gemini" }]} />
                        <div className="mt-1 text-[12px] leading-5 text-ink2">FLUX Fill：按遮罩精确补画，适合改动作、表情、背景、去掉多余的东西（走 fal）。<br />
                            Gemini：可以带商品实拍图，适合把手机修成我们的商品。自动：带商品图时用 Gemini，其他用 FLUX Fill。</div>
                    </div>
                    {hasProduct && <Checkbox checked={product} onChange={(e) => setProduct(e.target.checked)}>带上商品实拍图（涂的地方有手机时勾上，手机会照实拍画）</Checkbox>}
                    <div className="text-[12px] text-ink2">重绘后停在「关键帧待确认」，满意了点「用这张生成视频」；不满意可以接着局部重绘，或点「撤回重绘」回到上一版。</div>
                </div>
            </div>
        </Modal>
    );
}
