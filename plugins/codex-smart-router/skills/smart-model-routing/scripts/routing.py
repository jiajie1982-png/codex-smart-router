"""Local, deterministic task routing. No network requests or model tokens."""
from dataclasses import asdict, dataclass
import re

TIERS = ("luna", "terra", "sol", "astra")
MODELS = dict(zip(TIERS, ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra")))
EFFORTS = {"luna": "low", "terra": "medium", "sol": "high", "astra": "high"}


@dataclass(frozen=True)
class Route:
    tier: str
    model: str
    effort: str
    reason: str

    def to_dict(self):
        return asdict(self)


def classify(prompt, manual="auto", effort="auto", previous=None, failed=False):
    text = prompt.strip()
    if not text:
        raise ValueError("請先輸入要做的事情。")
    if len(text) > 100000:
        raise ValueError("單次輸入上限為 100,000 字元，請縮小工作範圍。")
    if manual not in ("auto", *TIERS):
        raise ValueError("未知的模型選項。")
    if effort not in ("auto", "low", "medium", "high", "xhigh"):
        raise ValueError("未知的推理強度。")
    # Inspect the user's request before long quoted material or fenced code.
    instruction = re.split(r"```|\n\s*\n|[：:]\s*\n", text, maxsplit=1)[0][:1200].lower()
    if manual != "auto":
        tier, reason = manual, "依你手動選擇的模型。"
    elif re.search(r"^(?:請|幫我|please\s+)?\s*(?:繼續|接著|好|可以|continue|go on|yes)[。.!！\s]*$", text, re.I) and previous:
        tier, reason = previous.tier, "這是延續上一項工作的簡短回覆，保留上一輪模型。"
    elif re.search(r"^(?:請|幫我|請幫我|please\s+)?\s*(?:把.{0,30})?(?:翻譯|翻成|translate|摘要|summarize|整理成表格|擷取|extract|分類|classify)", instruction):
        tier, reason = "luna", "明確的翻譯、摘要或資料轉換，先用較省用量的 Luna。"
    elif re.search(r"(?:系統|整體|分散式|跨系統|多服務|全新).{0,8}(?:架構|重構)|架構.{0,8}(?:設計|遷移)|distributed\s+(?:system|architecture)|system\s+architecture|跨服務.{0,12}(?:死鎖|資料一致性)|從零.{0,12}(?:完整系統|平台)", instruction):
        tier, reason = "astra", "涉及系統架構或跨服務的整體設計，需要較深入的推理。"
    elif re.search(r"複雜|跨檔案|跨模組|根因|安全.{0,5}(?:審查|漏洞|稽核)|競態|死鎖|記憶體洩漏|深度研究|大型重構|root\s+cause|race\s+condition|deadlock|memory\s+leak|security\s+(?:review|audit)|complex|multi.file|deep\s+research", instruction):
        tier, reason = "sol", "複雜除錯、跨檔案分析或深入研究，使用 Sol。"
    elif re.search(r"錯字|排版|格式轉換|重新命名|改名|typo|reformat|rename|^你好[！!。\s]*$|^hi[!\s]*$", instruction):
        tier, reason = "luna", "範圍明確的簡單工作，使用 Luna。"
    else:
        tier, reason = "terra", "一般工作或描述尚不明確，使用平衡的 Terra。"
    retry = failed or bool(re.search(r"仍然失敗|還是失敗|依然失敗|還是不行|沒有修好|still\s+(?:fails?|broken|not working)", instruction))
    if manual == "auto" and previous and retry:
        level = min(TIERS.index(previous.tier) + 1, len(TIERS) - 1)
        if level > TIERS.index(tier):
            tier = TIERS[level]
        reason = "你回報前一輪仍未解決，這一輪提高一級；不會自行重跑已做過的操作。"
    return Route(tier, MODELS[tier], EFFORTS[tier] if effort == "auto" else effort, reason)


def validate_available(route, catalog):
    model = next((x for x in catalog if x.get("model", x.get("id")) == route.model), None)
    if model is None:
        raise ValueError(f"目前帳號的模型清單沒有 {route.model}，請在模型選單手動選擇可用模型。")
    efforts = {x["reasoningEffort"] for x in model.get("supportedReasoningEfforts", [])}
    if route.effort not in efforts:
        raise ValueError(f"{route.model} 未提供 {route.effort} 推理強度，請換一個強度。")
    return route
