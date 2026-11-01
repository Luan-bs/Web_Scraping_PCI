from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    from backend.pr_cities import PR_CITIES
except ImportError:
    from pr_cities import PR_CITIES

# Garante saída UTF-8 no terminal do Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Coordenadas de referência: Toledo - PR
TOLEDO_COORDS = PR_CITIES["Toledo"]  # (-24.7246, -53.7412)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Fontes do PCI Concursos a serem combinadas
PCI_SOURCES = [
    ("TI", "https://www.pciconcursos.com.br/vagas/tecnologia-da-informacao"),
    ("TI", "https://www.pciconcursos.com.br/vagas/analista-de-sistemas"),
    ("TI", "https://www.pciconcursos.com.br/vagas/analista-de-tecnologia-da-informacao"),
    ("TI", "https://www.pciconcursos.com.br/vagas/tecnico-de-informatica"),
    ("TI", "https://www.pciconcursos.com.br/vagas/tecnico-em-informatica"),
    ("SUL", "https://www.pciconcursos.com.br/concursos/sul/"),
    ("NACIONAL", "https://www.pciconcursos.com.br/concursos/nacional/"),
]

# Expressão regular para identificar cargos de TI (Superior e Técnico/Médio)
TI_ROLE_REGEX = re.compile(
    r"("
    r"tecnologia da informa[cç][aã]o|"
    r"\bti\b|"
    r"inform[aá]tica|"
    r"an[aá]lise de sistemas|"
    r"analista de sistemas|"
    r"desenvolvimento de sistemas|"
    r"desenvolvedor|"
    r"programador|"
    r"ci[eê]ncia da computa[cç][aã]o|"
    r"engenharia de computa[cç][aã]o|"
    r"engenharia de software|"
    r"engenheiro de software|"
    r"sistemas de informa[cç][aã]o|"
    r"ci[eê]ncia de dados|"
    r"cientista de dados|"
    r"banco de dados|"
    r"infraestrutura de ti|"
    r"redes de computadores|"
    r"seguran[cç]a da informa[cç][aã]o|"
    r"cibern[eé]tica|"
    r"suporte t[eé]cnico|"
    r"suporte em tecnologia|"
    r"processamento de dados|"
    r"governan[cç]a de ti"
    r")",
    re.IGNORECASE,
)

# Expressão regular para excluir vagas de Professor / Docente
PROFESSOR_REGEX = re.compile(
    r"\b(professor|docente|magist[eé]rio)\b",
    re.IGNORECASE,
)

# Padrões de órgãos/títulos listados em "Nacional" mas restritos a outros estados (sem prova no PR)
OTHER_REGION_TITLE_REGEX = re.compile(
    r"("
    r"\btrf\s*[-–]?\s*[12356][ªa]?\b|"
    r"tribunal regional federal da [12356][ªa] regi[aã]o|"
    r"\btrt\s*[-–]?\s*(?:[1-8]|1[0-9]|2[0-4])[ªa]?\b|"
    r"\bcom[1234679][ºo]dn\b|"
    r"\b[1234679][ºo]\s*distrito naval\b|"
    r"\b(?:[12346789]|1[012])[ªa]\s*regi[aã]o militar\b|"
    r"\b[12346789][ªa]\s*rm\b|"
    r"\bcrbio[-–\s]*0?[12345689]\b|"
    r"\bcrn[-–\s]*0?[12345678]\b|"
    r"\bminas gerais\b|"
    r"\bmgs\b"
    r")",
    re.IGNORECASE,
)


def normalize_text(text: str) -> str:
    """Remove acentos e converte para minúsculas para comparação."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


# Mapa pré-normalizado de municípios do PR: nome_sem_acento -> (Nome Original, (lat, lon))
NORMALIZED_PR_CITIES: list[tuple[str, str, tuple[float, float]]] = sorted(
    [(normalize_text(name), name, coords) for name, coords in PR_CITIES.items()],
    key=lambda x: len(x[0]),
    reverse=True,  # Nomes compostos maiores primeiro (ex: "São José dos Pinhais" antes de "Pinhais")
)


def haversine_km(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    """Calcula a distância em linha reta (km) entre duas coordenadas (lat, lon)."""
    lat1, lon1 = map(math.radians, coord1)
    lat2, lon2 = map(math.radians, coord2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(6371.0 * 2 * math.asin(math.sqrt(a)), 1)


def parse_registration_status(prazo_text: str, today: dt.date) -> tuple[bool, str, str]:
    """
    Analisa o texto de prazo do PCI (ex: '10/11/2026', '04 a 23/11/2026', '03/11 a 03/12/2026').
    Retorna: (esta_ativo, status_inscricao, data_fim_iso)
    """
    clean = " ".join(prazo_text.split())
    full_dates = re.findall(r"(\d{2})/(\d{2})/(\d{4})", clean)
    if not full_dates:
        return False, "Encerrada", ""

    # A última data completa é sempre a data final de inscrição
    end_d, end_m, end_y = map(int, full_dates[-1])
    try:
        end_date = dt.date(end_y, end_m, end_d)
    except ValueError:
        return False, "Encerrada", ""

    if end_date < today:
        return False, "Encerrada", end_date.isoformat()

    # Verifica se há data de início explícita
    start_date: dt.date | None = None
    if len(full_dates) >= 2:
        st_d, st_m, st_y = map(int, full_dates[0])
        try:
            start_date = dt.date(st_y, st_m, st_d)
        except ValueError:
            start_date = None
    else:
        # Padrões como "03/11 a 03/12/2026" ou "04 a 23/11/2026"
        m_day_month = re.search(r"(\d{2})/(\d{2})\s*a\s*\d{2}/\d{2}/\d{4}", clean)
        m_day_only = re.search(r"(\d{2})\s*a\s*\d{2}/(\d{2})/(\d{4})", clean)
        try:
            if m_day_month:
                start_date = dt.date(end_y, int(m_day_month.group(2)), int(m_day_month.group(1)))
            elif m_day_only:
                start_date = dt.date(int(m_day_only.group(3)), int(m_day_only.group(2)), int(m_day_only.group(1)))
        except ValueError:
            start_date = None

    if start_date and today < start_date:
        return True, "Abre em breve", end_date.isoformat()

    return True, "Aberta", end_date.isoformat()


def is_restricted_to_other_states(orgao: str, title: str, article_text: str) -> bool:
    """
    Verifica se um concurso listado sem UF (Nacional/Regional no PCI) é exclusivo
    de outros estados onde não há aplicação de prova no Paraná.
    """
    combined_header = f"{orgao} {title}"
    if OTHER_REGION_TITLE_REGEX.search(combined_header):
        return True

    # Títulos com siglas de outros estados (ex: "TRF3 - SP/MS", "Marinha - AM e RO")
    if re.search(r"\s[-–]\s*(?:AC|AL|AM|AP|BA|CE|DF|ES|GO|MA|MG|MS|MT|PA|PB|PE|PI|RJ|RN|RO|RR|RS|SC|SE|SP|TO)(?:/|\s+e\s+|\b)", title):
        if not re.search(r"\bPR\b|Paran[aá]", title, re.IGNORECASE):
            return True

    # Verifica no texto da notícia se as provas/localidades são restritas apenas a outros estados
    norm_article = normalize_text(article_text)
    if "parana" in norm_article or "curitiba" in norm_article or "/pr" in norm_article or "- pr" in norm_article:
        return False

    # Se menciona explicitamente que as provas ou vagas são apenas em cidades/estados específicos fora do PR
    other_state_markers = re.findall(r"/\s*(ac|al|am|ap|ba|ce|df|es|go|ma|mg|ms|mt|pa|pb|pe|pi|rj|rn|ro|rr|rs|sc|se|sp|to)\b", norm_article)
    if other_state_markers and "pr" not in other_state_markers:
        return True

    if re.search(r"no estado d[eo]\s+(minas gerais|sao paulo|rio de janeiro|mato grosso|bahia|goias|rio grande do sul|santa catarina)", norm_article):
        return True

    return False


def extract_ti_roles_from_article(soup: BeautifulSoup, fallback_details: str) -> list[str]:
    """
    Extrai os cargos de TI listados na notícia do PCI, ignorando cargos de Professor/Docente.
    """
    article = soup.find("article") or soup.find("div", id="noticia")
    if not article:
        return []

    roles: list[str] = []
    # No PCI Concursos, os cargos do edital ficam listados em tags <li> dentro do <article>
    for li in article.find_all("li"):
        text = " ".join(li.get_text(" ", strip=True).split())
        if not text:
            continue
        if TI_ROLE_REGEX.search(text) and not PROFESSOR_REGEX.search(text):
            if text not in roles:
                roles.append(text)

    # Caso a notícia não use <li> mas seja um edital específico de TI no resumo/parágrafos
    if not roles:
        for p in article.find_all(["p", "h1", "h2"]):
            text = " ".join(p.get_text(" ", strip=True).split())
            if len(text) < 220 and TI_ROLE_REGEX.search(text) and not PROFESSOR_REGEX.search(text):
                if any(k in text.lower() for k in ["analista", "técnico", "tecnico", "auditor", "especialidade", "cargo", "engenheiro", "desenvolvedor", "programador", "instrutor"]):
                    roles.append(text)

    if not roles and TI_ROLE_REGEX.search(fallback_details) and not PROFESSOR_REGEX.search(fallback_details):
        roles.append(fallback_details)

    return roles


def find_closest_pr_city(orgao: str, title: str, article_text: str) -> tuple[str, float]:
    """
    Identifica a(s) cidade(s) do Paraná mencionadas no concurso e retorna a mais próxima
    de Toledo - PR junto com a distância em km.
    Prioriza o nome do órgão/título; se for estadual (ex: UNIOESTE, UFPR), busca no texto.
    """
    header_norm = normalize_text(f"{orgao} {title}")
    matched_header: list[tuple[str, float]] = []

    for norm_city, orig_city, coords in NORMALIZED_PR_CITIES:
        # Evita falsos positivos com nomes muito curtos que são palavras comuns
        if len(norm_city) <= 3:
            continue
        pattern = rf"\b{re.escape(norm_city)}\b"
        if re.search(pattern, header_norm):
            dist = haversine_km(TOLEDO_COORDS, coords)
            matched_header.append((orig_city, dist))

    if matched_header:
        matched_header.sort(key=lambda x: x[1])
        return matched_header[0]

    # Se não achou no título (ex: UNIOESTE, UFPR, SANEPAR, TJ-PR), procura no texto da notícia
    body_norm = normalize_text(article_text)
    matched_body: list[tuple[str, float]] = []
    for norm_city, orig_city, coords in NORMALIZED_PR_CITIES:
        if len(norm_city) <= 4:
            continue
        pattern = rf"\b{re.escape(norm_city)}\b"
        if re.search(pattern, body_norm):
            dist = haversine_km(TOLEDO_COORDS, coords)
            matched_body.append((orig_city, dist))

    if matched_body:
        matched_body.sort(key=lambda x: x[1])
        return matched_body[0]

    # Fallback para órgãos estaduais do PR sem cidade especificada: Curitiba
    curitiba_dist = haversine_km(TOLEDO_COORDS, PR_CITIES["Curitiba"])
    return ("Curitiba", curitiba_dist)


def parse_salary_float(salario_str: str) -> float:
    """Converte string '20.013,11' em float 20013.11 para ordenação."""
    if not salario_str or salario_str == "Não informado":
        return 0.0
    try:
        cleaned = salario_str.replace(".", "").replace(",", ".")
        return float(cleaned)
    except ValueError:
        return 0.0


def scrape_pci_ti_parana() -> list[dict]:
    today = dt.date.today()
    candidates: dict[str, dict] = {}

    for source_type, url in PCI_SOURCES:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception as exc:
            print(f"[AVISO] Falha ao acessar {url}: {exc}", file=sys.stderr)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.find_all("div", class_="ca"):
            link_tag = item.find("a")
            if not link_tag:
                continue

            link = link_tag.get("href", "").strip()
            if not link or link in candidates:
                continue

            uf_tag = item.find("div", class_="cc")
            uf = uf_tag.get_text(strip=True) if uf_tag else ""
            # Limpa caracteres invisíveis ou espaços
            uf = re.sub(r"[^A-Z]", "", uf.upper())

            # Queremos apenas PR ou Nacionais (UF vazia)
            if uf not in ("PR", ""):
                continue

            prazo_tag = item.find("div", class_="ce")
            prazo_raw = prazo_tag.get_text(" ", strip=True) if prazo_tag else ""
            is_active, status_inscricao, data_fim_iso = parse_registration_status(prazo_raw, today)
            if not is_active:
                continue

            orgao = link_tag.get_text(strip=True)
            title = link_tag.get("title", "") or orgao

            detalhes_tag = item.find("div", class_="cd")
            detalhes = detalhes_tag.get_text(" | ", strip=True) if detalhes_tag else ""

            # Extrai escolaridade (Médio / Técnico / Superior)
            spans = detalhes_tag.find_all("span") if detalhes_tag else []
            escolaridade = spans[-1].get_text(" ", strip=True) if spans else "Consultar edital"

            salario_match = re.search(r"R\$\s?([\d\.,]+)", detalhes)
            salario_max = salario_match.group(1) if salario_match else "Não informado"

            candidates[link] = {
                "orgao": orgao,
                "titulo": title,
                "uf": uf if uf == "PR" else "BR",
                "escopo": "PR" if uf == "PR" else "NACIONAL",
                "salario_ate": salario_max,
                "salario_num": parse_salary_float(salario_max),
                "detalhes": detalhes,
                "escolaridade": escolaridade,
                "inscricoes_ate": prazo_raw,
                "status_inscricao": status_inscricao,
                "data_fim_iso": data_fim_iso,
                "link": link,
                "source_type": source_type,
            }

    results: list[dict] = []

    for link, cand in candidates.items():
        try:
            art_resp = requests.get(link, headers=HEADERS, timeout=15)
            art_resp.raise_for_status()
            art_soup = BeautifulSoup(art_resp.text, "html.parser")
        except Exception as exc:
            print(f"[AVISO] Falha ao ler notícia {link}: {exc}", file=sys.stderr)
            continue

        article_tag = art_soup.find("article") or art_soup.find("div", id="noticia")
        article_text = article_tag.get_text("\n", strip=True) if article_tag else ""

        # Se for listado como NACIONAL (UF vazia), descarta se for exclusivo de outros estados fora do PR
        if cand["escopo"] == "NACIONAL":
            if is_restricted_to_other_states(cand["orgao"], cand["titulo"], article_text):
                continue

        # Extrai cargos de TI (excluindo vagas de Professor/Docente)
        cargos_ti = extract_ti_roles_from_article(art_soup, cand["detalhes"])
        if not cargos_ti:
            continue

        if cand["escopo"] == "PR":
            cidade_base, dist_km = find_closest_pr_city(cand["orgao"], cand["titulo"], article_text)
        else:
            cidade_base = "Nacional (Prova no PR / Capitais)"
            dist_km = None

        results.append(
            {
                "orgao": cand["orgao"],
                "titulo": cand["titulo"],
                "escopo": cand["escopo"],
                "uf": cand["uf"],
                "cidade_base": cidade_base,
                "distancia_toledo_km": dist_km,
                "status_inscricao": cand["status_inscricao"],
                "inscricoes_ate": cand["inscricoes_ate"],
                "data_fim_iso": cand["data_fim_iso"],
                "salario_ate": cand["salario_ate"],
                "salario_num": cand["salario_num"],
                "escolaridade": cand["escolaridade"],
                "detalhes": cand["detalhes"],
                "cargos_ti": cargos_ti,
                "link": cand["link"],
            }
        )

    # Ordenação:
    # 1. Nacionais no topo (escopo == "NACIONAL" vem antes de "PR")
    # 2. Para PR: menor distância até Toledo - PR (distancia_toledo_km crescente)
    # 3. Desempate: Inscrições "Aberta" antes de "Abre em breve", depois maior salário
    results.sort(
        key=lambda x: (
            0 if x["escopo"] == "NACIONAL" else 1,
            x["distancia_toledo_km"] if x["distancia_toledo_km"] is not None else -1.0,
            0 if x["status_inscricao"] == "Aberta" else 1,
            -x["salario_num"],
        )
    )

    return results


def save_frontend_json(concursos: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    now_str = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
    payload = {
        "atualizado_em": now_str,
        "cidade_referencia": "Toledo - PR",
        "coordenadas_referencia": {
            "lat": TOLEDO_COORDS[0],
            "lon": TOLEDO_COORDS[1],
        },
        "total": len(concursos),
        "concursos": concursos,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    print("Buscando editais de TI abertos no PCI Concursos (Nacionais + Paraná)...")
    concursos = scrape_pci_ti_parana()

    root_dir = Path(__file__).resolve().parent.parent
    json_path = root_dir / "frontend" / "concursos.json"
    save_frontend_json(concursos, json_path)

    print(f"\nTotal de concursos de TI encontrados: {len(concursos)}")
    print(f"Arquivo JSON salvo em: {json_path}\n")

    if not concursos:
        print("Nenhum concurso aberto encontrado no momento.")
        return

    rows = []
    for idx, c in enumerate(concursos, start=1):
        local_str = (
            "Nacional (Topo)"
            if c["escopo"] == "NACIONAL"
            else f"{c['cidade_base']}/PR ({c['distancia_toledo_km']} km)"
        )
        rows.append(
            {
                "#": idx,
                "Escopo / Distância Toledo": local_str,
                "Órgão": c["orgao"],
                "Salário Até": f"R$ {c['salario_ate']}" if c["salario_ate"] != "Não informado" else "Não inf.",
                "Status": f"{c['status_inscricao']} ({c['inscricoes_ate']})",
                "Cargos TI": "; ".join(c["cargos_ti"])[:70],
            }
        )

    df = pd.DataFrame(rows)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
