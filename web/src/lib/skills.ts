/** 投放 Agent 的 Skill：一张卡片 = 一个投放场景，点击后带着指令进入画布，由 Agent 出计划。 */
export interface Skill {
    id: string;
    category: "剧本" | "视频" | "评测" | "投放" | "优化";
    title: string;
    desc: string;
    prompt: string;
    uses: string;
    gradient: string;
    hot?: boolean;
}

export const SKILLS: Skill[] = [
    { id: "wash", category: "剧本", title: "竞品爆款洗剧本", desc: "借竞品爆款的钩子与节奏，换成传音卖点，批量写剧本", prompt: "用 @爆款 #12 给小商贩写 3 个续航剧本", uses: "2.3k", gradient: "linear-gradient(135deg,#ff7a45,#7c5cff)", hot: true },
    { id: "pidgin", category: "剧本", title: "皮钦语本土化", desc: "把剧本改写成尼日利亚口语，替换场景、服装和笑点", prompt: "给小商贩写 2 个续航剧本，口播用皮钦语", uses: "1.6k", gradient: "linear-gradient(135deg,#2bc48a,#13c2c2)" },
    { id: "student", category: "剧本", title: "学生党拍照系列", desc: "夜拍对比钩子，面向 18–24 岁学生", prompt: "给学生写 3 个拍照剧本", uses: "1.2k", gradient: "linear-gradient(135deg,#9254de,#3e8bff)" },
    { id: "ramadan", category: "剧本", title: "斋月团聚营销", desc: "巴基斯坦年轻家庭，斋月夜晚团聚与合影", prompt: "给年轻家庭写 3 个拍照剧本", uses: "860", gradient: "linear-gradient(135deg,#f5a524,#eb2f96)" },
    { id: "video", category: "视频", title: "剧本一键成片", desc: "按镜调用 Seedance，产品镜头用官方素材，自动配音与字幕", prompt: "生成视频", uses: "3.0k", gradient: "linear-gradient(135deg,#3e8bff,#7c5cff)", hot: true },
    { id: "eval", category: "评测", title: "40 人虚拟评测", desc: "40 个本地用户画像逐秒观看，预测点击率与完播率", prompt: "跑评测", uses: "1.8k", gradient: "linear-gradient(135deg,#f5a524,#ff7a45)" },
    { id: "best", category: "评测", title: "找出最佳素材", desc: "对比评测结果，定位预测点击率最高的素材", prompt: "哪个视频预测 CTR 最高？", uses: "720", gradient: "linear-gradient(135deg,#36cfc9,#2bc48a)" },
    { id: "deliver", category: "投放", title: "TikTok 投放方案", desc: "按建议人群建广告组，测试期预算与护栏一次配好", prompt: "生成投放方案", uses: "1.1k", gradient: "linear-gradient(135deg,#2bc48a,#3e8bff)" },
    { id: "summary", category: "优化", title: "项目进度复盘", desc: "汇总画布上各模块状态与待审核事项", prompt: "总结进度", uses: "540", gradient: "linear-gradient(135deg,#eb2f96,#7c5cff)" },
];

export const TOOLS = [
    { label: "Seedance 2.5", hint: "视频生成模型", prompt: "生成视频" },
    { label: "Gemini 2.5", hint: "多模态理解", prompt: "跑评测" },
    { label: "TikTok Ads", hint: "已连接", to: "/delivery" },
    { label: "剧本生成", hint: "洗爆款结构", prompt: "给小商贩写 3 个续航剧本" },
    { label: "本土化", hint: "皮钦语 / 乌尔都语", prompt: "给小商贩写 2 个续航剧本，口播用皮钦语" },
    { label: "视频生成", hint: "按镜成片", prompt: "生成视频" },
    { label: "40 人评测", hint: "预测 CTR", prompt: "跑评测" },
    { label: "智能投放", hint: "方案 + 护栏", prompt: "生成投放方案" },
] as const;
