import { MarketSandbox } from "@/components/sandbox/market-sandbox";

/** 全屏的全球营销沙盘 */
export default function SandboxPage() {
    return (
        <div className="mx-auto max-w-[1600px] px-6 py-5 max-[900px]:px-4">
            <MarketSandbox full />
        </div>
    );
}
