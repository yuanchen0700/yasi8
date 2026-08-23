import random

PALETTE = [
    "#2563eb", "#7c3aed", "#db2777", "#ea580c",
    "#059669", "#0284c7", "#e11d48", "#9333ea",
]

def cover_class(cid):
    return PALETTE[cid % len(PALETTE)]

def cover_emoji(category):
    return "📝" if category == "笔记" else "🛠️"
