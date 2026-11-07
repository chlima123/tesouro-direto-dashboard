#!/usr/bin/env python3
"""Harness funcional do painel Tesouro Direto (Chrome real via Playwright).

Uso: python3 verificar.py [url]   (default: file://<pasta>/index.html)

Prova, no artefato que o usuário abre: a senha do gate, a contagem de linhas, KPIs
recomputados do próprio HTML, contadores das abas, filtros medidos isoladamente
(com os outros campos zerados), busca, ordenação, simulador e console limpo.
"""
import glob
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, "index.html")
URL = sys.argv[1] if len(sys.argv) > 1 else "file://" + LOCAL

fails, oks = [], []


def check(nome, cond, detalhe=""):
    (oks if cond else fails).append(nome)
    print(("  OK   " if cond else "  FALHA") + f" {nome}" + (f" — {detalhe}" if detalhe else ""))


def abrir(pw):
    try:
        return pw.chromium.launch(channel="chrome")
    except Exception:
        padroes = [
            "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac-*/chrome-headless-shell",
            "~/Library/Caches/ms-playwright/chromium-*/chrome-mac-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            "~/Library/Caches/ms-playwright/chromium-*/chrome-mac-*/Chromium.app/Contents/MacOS/Chromium",
        ]
        cands = [c for p in padroes for c in sorted(glob.glob(os.path.expanduser(p)))]
        if not cands:
            raise
        return pw.chromium.launch(executable_path=cands[-1])


def extrair(url):
    import urllib.request
    if url.startswith("file://"):
        return open(url[7:], encoding="utf-8").read()
    req = urllib.request.Request(url + ("&" if "?" in url else "?") + "cb=" + str(os.getpid()),
                                 headers={"Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8")


html = extrair(URL)
DATA = json.loads(re.search(r"const DATA = (\[.*?\]);", html, re.S).group(1))  # type: ignore[union-attr]
SENHA = re.search(r'pass !== "([^"]+)"', html).group(1)  # type: ignore[union-attr]
base = DATA[0]["data_base"]
selic = [d for d in DATA if d["categoria"] == "selic"]
prefix = [d for d in DATA if d["categoria"] == "prefixado"]
ipca = [d for d in DATA if d["categoria"] == "ipca"]
exp = {
    "total": len(DATA),
    "maxpre": f'{max(d["taxa_compra"] for d in prefix):.2f}'.replace(".", ",") + "%",
    "maxipca": "IPCA + " + f'{max(d["taxa_compra"] for d in ipca):.2f}'.replace(".", ",") + "%",
    "selic": "Selic + " + f'{sum(d["taxa_compra"] for d in selic)/len(selic):.2f}'.replace(".", ",") + "%",
    "prazo": f'{min(d["ano_vencimento"] for d in DATA)} → {max(d["ano_vencimento"] for d in DATA)}',
}
print(f"URL: {URL}\nbase={base} linhas esperadas={exp['total']}")

with sync_playwright() as pw:
    br = abrir(pw)
    pg = br.new_page(viewport={"width": 1440, "height": 900})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)

    # 1) senha errada nega acesso
    pg.once("dialog", lambda d: d.accept("senha-errada"))
    pg.goto(URL, wait_until="load")
    pg.wait_for_timeout(400)
    check("senha errada bloqueia", "Acesso negado" in pg.content() and
          pg.eval_on_selector_all("#tableBody tr", "e=>e.length") == 0)

    # 2) senha correta renderiza
    erros.clear()  # a página negada derruba o body e o DOMContentLoaded do painel acusa null — não é erro da versão boa
    pg.on("dialog", lambda d: d.accept(SENHA))
    pg.goto(URL, wait_until="load")
    pg.wait_for_timeout(900)
    linhas = pg.eval_on_selector_all("#tableBody tr", "e=>e.length")
    check("linhas da tabela", linhas == exp["total"], f"{linhas} != {exp['total']}")
    check("badge de base", pg.inner_text("#liveBadge").strip().endswith(base),
          pg.inner_text("#liveBadge").strip())
    for kpi, valor in (("kpiTotal", str(exp["total"])), ("kpiMaxPre", exp["maxpre"]),
                       ("kpiMaxIpca", exp["maxipca"]), ("kpiSelic", exp["selic"]),
                       ("kpiPrazo", exp["prazo"])):
        txt = pg.inner_text("#" + kpi).strip()
        check(f"KPI {kpi}", txt == valor, f"{txt!r} != {valor!r}")
    check("rodapé KPI prazo", "58 anos" in pg.inner_text(".kpi-grid"),
          pg.inner_text(".kpi-grid").splitlines()[-1][:60])

    # 3) contadores das abas
    for cat, n in [("todos", len(DATA))] + [(c, sum(1 for d in DATA if d["categoria"] == c))
                                            for c in ("selic", "prefixado", "ipca", "renda_mais", "educa_mais")]:
        txt = pg.inner_text(f"#count-{cat}").strip()
        check(f"aba {cat}", txt == str(n), f"{txt} != {n}")

    # 4) filtro semestral isolado (busca zerada, categoria todos)
    def filtrar():
        pg.fill("#searchInput", "")
        pg.dispatch_event("#searchInput", "input")
        pg.wait_for_timeout(120)
        return pg.eval_on_selector_all("#tableBody tr td:first-child .badge-cat", "e=>e.map(x=>x.parentElement.innerText)")

    pg.select_option("#selectSemestral", "sem")
    pg.wait_for_timeout(150)
    sem = pg.eval_on_selector_all("#tableBody tr", "e=>e.length")
    check("filtro sem juros semestrais", sem == sum(1 for d in DATA if not d["semestral"]), str(sem))
    pg.select_option("#selectSemestral", "com")
    pg.wait_for_timeout(150)
    com = pg.eval_on_selector_all("#tableBody tr", "e=>e.length")
    check("filtro com juros semestrais", com == sum(1 for d in DATA if d["semestral"]), str(com))
    check("filtro sem+com soma o total", sem + com == len(DATA), f"{sem}+{com}")
    pg.select_option("#selectSemestral", "todos")

    # 5) busca
    pg.fill("#searchInput", "educa")
    pg.wait_for_timeout(200)
    busca = pg.eval_on_selector_all("#tableBody tr", "e=>e.length")
    check("busca 'educa'", busca == sum(1 for d in DATA if "educa" in d["nome"].lower()), str(busca))
    pg.fill("#searchInput", "2084")
    pg.wait_for_timeout(200)
    check("busca '2084'", pg.eval_on_selector_all("#tableBody tr", "e=>e.length") ==
          sum(1 for d in DATA if "2084" in d["nome"] or "2084" in d["vencimento"]))
    pg.fill("#searchInput", "")
    pg.dispatch_event("#searchInput", "input")
    pg.wait_for_timeout(150)

    # 6) ordenações
    pg.select_option("#selectOrder", "taxa_desc")
    pg.wait_for_timeout(200)
    primeira = pg.inner_text("#tableBody tr:first-child .rate-val").strip()
    check("ordem maior taxa", primeira == max(prefix, key=lambda d: d["taxa_compra"])["taxa_str"], primeira)
    pg.select_option("#selectOrder", "venc_asc")
    pg.wait_for_timeout(200)
    prim_venc = pg.inner_text("#tableBody tr:first-child td:nth-child(2)").strip()
    check("ordem vencimento asc", prim_venc == min(d["vencimento"] for d in DATA), prim_venc)
    pg.select_option("#selectOrder", "venc_desc")
    pg.wait_for_timeout(200)
    check("ordem vencimento desc", pg.inner_text("#tableBody tr:first-child td:nth-child(2)").strip() ==
          max(d["vencimento"] for d in DATA))
    pg.select_option("#selectOrder", "venc_asc")
    pg.wait_for_timeout(150)

    # 7) painel de detalhe + simulador
    pg.click("#tableBody tr:nth-child(3)")
    pg.wait_for_timeout(250)
    check("painel mostra título da linha", pg.inner_text("#panelTitle").strip() in
          [d["nome"] for d in DATA], pg.inner_text("#panelTitle").strip())
    prazo = pg.inner_text("#panelPrazoDias")
    check("prazo restante calculado", "dias" in prazo and "0 dias" != prazo, prazo)
    pg.fill("#simAporteInput", "10000")
    pg.dispatch_event("#simAporteInput", "input")
    pg.wait_for_timeout(200)
    check("simulador responde", "R$" in pg.inner_text("#simResgateVal"), pg.inner_text("#simResgateVal"))

    # 8) gráfico comparativo
    barras = pg.eval_on_selector_all("#barsContainer .bar-row", "e=>e.length")
    check("gráfico com barras", barras >= 5, str(barras))

    # 9) console limpo
    check("console sem erros", not erros, "; ".join(erros[:3]))

    # 10) mobile 390 sem overflow horizontal
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.wait_for_timeout(400)
    over = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    check("mobile 390 sem overflow", over <= 1, f"overflow={over}px")

    pg.screenshot(path="/tmp/tesouro_390.png", full_page=False)
    pg.set_viewport_size({"width": 1440, "height": 900})
    pg.wait_for_timeout(200)
    pg.screenshot(path="/tmp/tesouro_1440.png")
    br.close()

print(f"\n{len(oks)} OK · {len(fails)} FALHA")
sys.exit(1 if fails else 0)
