#!/usr/bin/env python3
"""Regenera o bloco de dados (e os números escritos à mão) do Tesouro Direto dashboard.

Fonte oficial: CSV diário do Tesouro Transparente (CKAN, sem WAF).
Substitui APENAS o que depende do dado; o gate de senha e o layout ficam intactos.
Aborta alto se qualquer alvo de substituição não for encontrado.
"""
import csv
import io
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, "index.html")
CSV_LOCAL = os.path.expanduser("~/.hermes/cache/scratch/tesouro/precos.csv")
CSV_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)

# Atributos estáticos por família de título (cor/indexador/rótulo) — herdados do
# desenho original do painel. Tipo novo de título DEVE entrar aqui (falha alta).
FAMILIA = {
    "Tesouro Selic": dict(categoria="selic", categoria_nome="Tesouro Selic",
                          cor="#10B981", indexador="Taxa Selic"),
    "Tesouro Prefixado": dict(categoria="prefixado", categoria_nome="Prefixado",
                              cor="#F59E0B", indexador="Prefixado"),
    "Tesouro Prefixado com Juros Semestrais": dict(categoria="prefixado", categoria_nome="Prefixado",
                                                   cor="#F59E0B", indexador="Prefixado"),
    "Tesouro IPCA+": dict(categoria="ipca", categoria_nome="Tesouro IPCA+",
                          cor="#3B82F6", indexador="IPCA + Taxa Fixa"),
    "Tesouro IPCA+ com Juros Semestrais": dict(categoria="ipca", categoria_nome="Tesouro IPCA+",
                                               cor="#3B82F6", indexador="IPCA + Taxa Fixa"),
    "Tesouro IGPM+ com Juros Semestrais": dict(categoria="igpm", categoria_nome="Tesouro IGPM+",
                                               cor="#6366F1", indexador="IGP-M + Taxa Fixa"),
    "Tesouro Renda+ Aposentadoria Extra": dict(categoria="renda_mais",
                                               categoria_nome="Tesouro Renda+ (Aposentadoria)",
                                               cor="#8B5CF6", indexador="IPCA + Renda Aposentadoria"),
    "Tesouro Educa+": dict(categoria="educa_mais", categoria_nome="Tesouro Educa+ (Estudos)",
                           cor="#EC4899", indexador="IPCA + Renda Educação"),
}


def num(s):
    return float(s.strip().replace(".", "").replace(",", ".")) if s.strip() else 0.0


def baixar_csv():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(CSV_URL, headers={"User-Agent": "Mozilla/5.0 (Hermes/1.0)"})
    raw = urllib.request.urlopen(req, context=ctx, timeout=120).read()
    os.makedirs(os.path.dirname(CSV_LOCAL), exist_ok=True)
    with open(CSV_LOCAL, "wb") as f:
        f.write(raw)
    return raw


def carregar_linhas(fresco):
    raw = baixar_csv() if fresco or not os.path.exists(CSV_LOCAL) else open(CSV_LOCAL, "rb").read()
    texto = raw.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(texto), delimiter=";"))
    bases = {r["Data Base"] for r in rows if r.get("Data Base")}
    base = max(bases, key=lambda d: datetime.strptime(d, "%d/%m/%Y"))
    return [r for r in rows if r["Data Base"] == base], base


def montar_itens(rows, base, ids_antigos):
    itens = []
    proximo = 1
    if ids_antigos:
        nums = [int(m.group(1)) for m in (re.match(r"tit-(\d+)$", i["id"]) for i in ids_antigos.values()) if m]
        proximo = max(nums) + 1 if nums else 1
    usados = set()
    for r in rows:
        tipo = r["Tipo Titulo"].strip()
        if tipo not in FAMILIA:
            raise SystemExit(f"FAMILIA sem mapeamento para tipo novo: {tipo!r} — pare e acrescente antes de publicar")
        fam = FAMILIA[tipo]
        venc = r["Data Vencimento"].strip()
        dt = datetime.strptime(venc, "%d/%m/%Y")
        taxa_c, taxa_v = num(r["Taxa Compra Manha"]), num(r["Taxa Venda Manha"])
        pu_c, pu_v = num(r["PU Compra Manha"]), num(r["PU Venda Manha"])
        semestral = "Juros Semestrais" in tipo
        if fam["categoria"] == "selic":
            sinal = "-" if taxa_c < 0 else "+"
            taxa_str = f"Selic {sinal} {abs(taxa_c):.2f}%"
        elif fam["categoria"] == "igpm":
            taxa_str = f"IGP-M + {taxa_c:.2f}%"
        elif fam["categoria"] in ("ipca", "renda_mais", "educa_mais"):
            taxa_str = f"IPCA + {taxa_c:.2f}%"
        else:
            taxa_str = f"{taxa_c:.2f}% a.a."

        chave = (tipo, venc)
        velho = ids_antigos.get(chave)
        if velho and velho["id"] not in usados:
            tid = velho["id"]
        else:
            tid = f"tit-{proximo}"
            proximo += 1
        usados.add(tid)

        itens.append({
            "id": tid,
            "nome": f"{tipo} {dt.year}",
            "tipo_completo": tipo,
            "categoria": fam["categoria"],
            "categoria_nome": fam["categoria_nome"],
            "cor": fam["cor"],
            "indexador": fam["indexador"],
            "taxa_compra": taxa_c,
            "taxa_venda": taxa_v,
            "taxa_str": taxa_str,
            "pu_compra": pu_c,
            "pu_venda": pu_v,
            "pu_base": num(r["PU Base Manha"]),
            "minimo": max(30.0, round(pu_c * 0.01, 2)),
            "vencimento": venc,
            "ano_vencimento": dt.year,
            "dt_venc_iso": dt.strftime("%Y-%m-%d"),
            "semestral": semestral,
            "data_base": base,
        })
    itens.sort(key=lambda i: (i["dt_venc_iso"], i["nome"]))
    return itens


def kpis(itens, base):
    pre = [i for i in itens if i["categoria"] == "prefixado"]
    ipca = [i for i in itens if i["categoria"] == "ipca"]
    selic = [i for i in itens if i["categoria"] == "selic"]
    maxpre = max(i["taxa_compra"] for i in pre)
    nomes_pre = [i["nome"].replace("Tesouro ", "").replace(" com Juros Semestrais", " com Juros")
                 for i in sorted(pre, key=lambda i: i["dt_venc_iso"]) if i["taxa_compra"] == maxpre]
    maxipca = max(i["taxa_compra"] for i in ipca)
    nome_ipca = next(i["nome"] for i in ipca if i["taxa_compra"] == maxipca)
    # "Spread Selic Médio": média real dos spreads de compra das LFTs
    spread = sum(i["taxa_compra"] for i in selic) / len(selic)
    ano_min = min(i["ano_vencimento"] for i in itens)
    ano_max = max(i["ano_vencimento"] for i in itens)
    base_dt = datetime.strptime(base, "%d/%m/%Y")
    prazos = [(datetime.strptime(i["vencimento"], "%d/%m/%Y") - base_dt).days / 365.25 for i in itens]
    meses = round(min(prazos) * 12)
    anos = round(max(prazos))
    return {
        "total": len(itens),
        "maxpre": f"{maxpre:.2f}".replace(".", ",") + "%",
        "maxpre_sub": " · ".join(nomes_pre),
        "maxipca": f"IPCA + {maxipca:.2f}".replace(".", ",") + "%",
        "maxipca_sub": nome_ipca,
        "selic": f"Selic + {spread:.2f}".replace(".", ",") + "%",
        "selic_sub": f"Pós-fixados LFT (Reserva) · {len(selic)} títulos",
        "prazo": f"{ano_min} → {ano_max}",
        "prazo_sub": f"De {meses} meses a {anos} anos de prazo",
        "datas": {"min": min(i["dt_venc_iso"] for i in itens),
                  "max": max(i["dt_venc_iso"] for i in itens)},
    }


def sub(html, padrao, novo, rotulo):
    novo_html, n = re.subn(padrao, novo, html, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"bake abortado: alvo não encontrado/ambíguo — {rotulo}")
    return novo_html


def main():
    fresco = True  # sempre baixa a base do dia; --cached usa o CSV em scratch
    if "--cached" in sys.argv:
        fresco = False

    html = open(HTML, encoding="utf-8").read()

    m = re.search(r"const DATA = (\[.*?\]);", html, re.S)
    if not m:
        raise SystemExit("bake abortado: const DATA não encontrado")
    antigos = json.loads(m.group(1))
    ids_antigos = {(i["tipo_completo"], i["vencimento"]): i for i in antigos}

    rows, base = carregar_linhas(fresco)
    itens = montar_itens(rows, base, ids_antigos)
    k = kpis(itens, base)

    novo_json = json.dumps(itens, ensure_ascii=False)
    html = sub(html, r"const DATA = \[.*?\];", lambda mm: "const DATA = " + novo_json + ";", "const DATA")
    html = sub(html, r'(id="liveBadge">🟢 Base: )\d{2}/\d{2}/\d{4}', r"\g<1>" + base, "liveBadge")
    html = sub(html, r'(id="kpiTotal">)\d+(</div>)', r"\g<1>" + str(k["total"]) + r"\g<2>", "kpiTotal")
    for campo, valor in (("kpiMaxPre", k["maxpre"]), ("kpiMaxIpca", k["maxipca"]),
                         ("kpiSelic", k["selic"]), ("kpiPrazo", k["prazo"])):
        html = sub(html, r'(id="%s">)[^<]*(</div>)' % campo,
                   lambda mm, v=valor: mm.group(1) + v + mm.group(2), campo)
    for campo, valor in (("kpiMaxPre", k["maxpre_sub"]), ("kpiMaxIpca", k["maxipca_sub"]),
                         ("kpiSelic", k["selic_sub"]), ("kpiPrazo", k["prazo_sub"])):
        html = sub(html, r'(id="%s">[^<]*</div>\s*<div class="kpi-subtext">)[^<]*(</div>)' % campo,
                   lambda mm, v=valor: mm.group(1) + v + mm.group(2), campo + " subtext")
    for cat in ("todos", "selic", "prefixado", "ipca", "renda_mais", "educa_mais"):
        n = k["total"] if cat == "todos" else sum(1 for i in itens if i["categoria"] == cat)
        html = sub(html, r'(id="count-%s">)\d+(</span>)' % cat,
                   lambda mm, v=n: mm.group(1) + str(v) + mm.group(2), "count-" + cat)
    html = sub(html, r'(id="tableCountLabel">Exibindo )\d+( títulos? públicos)',
               lambda mm: mm.group(1) + str(k["total"]) + " títulos públicos", "tableCountLabel")

    # Data de referência do JS (prazo restante / simulador) = dia seguinte ao da base
    ref = (datetime.strptime(base, "%d/%m/%Y") + timedelta(days=1)).strftime("%Y-%m-%d")
    html, n = re.subn(r"new Date\('\d{4}-\d{2}-\d{2}'\)", f"new Date('{ref}')", html)
    if n != 2:
        raise SystemExit(f"bake abortado: esperava 2 datas de referência no JS, achou {n}")

    # favicon inline: sem ele a produção acusa 404 de /favicon.ico no console
    if 'rel="icon"' not in html:
        html = html.replace("</title>", '</title>\n  <link rel="icon" href="data:," />', 1)

    open(HTML, "w", encoding="utf-8").write(html)

    print(f"base={base} titulos={k['total']} ref_js={ref}")
    print(f"KPI prefixado={k['maxpre']} ({k['maxpre_sub']})")
    print(f"KPI ipca={k['maxipca']} ({k['maxipca_sub']})  selic={k['selic']}  prazo={k['prazo']} ({k['prazo_sub']})")
    print(f"vencimentos: {k['datas']['min']} .. {k['datas']['max']}")
    por_cat = {}
    for i in itens:
        por_cat[i["categoria"]] = por_cat.get(i["categoria"], 0) + 1
    print("por categoria:", por_cat)


if __name__ == "__main__":
    main()
