let allConcursos = [];

const searchInput = document.getElementById("search-input");
const scopeFilter = document.getElementById("scope-filter");
const statusFilter = document.getElementById("status-filter");
const levelFilter = document.getElementById("level-filter");
const listContainer = document.getElementById("concursos-list");
const resultsInfo = document.getElementById("results-info");

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function updateStats(data) {
  const items = data.concursos || [];
  const total = items.length;
  const nacionais = items.filter((c) => c.escopo === "NACIONAL").length;
  const prItems = items.filter((c) => c.escopo === "PR");

  document.getElementById("stat-total").textContent = total;
  document.getElementById("stat-nacional").textContent = nacionais;
  document.getElementById("stat-pr").textContent = prItems.length;

  if (prItems.length > 0) {
    const closest = prItems[0];
    document.getElementById("stat-closest").textContent =
      `${closest.cidade_base} (${closest.distancia_toledo_km} km)`;
  } else {
    document.getElementById("stat-closest").textContent = "Nenhum no PR hoje";
  }

  if (data.atualizado_em) {
    document.getElementById("last-updated").textContent = data.atualizado_em;
  }
}

function renderList() {
  const query = searchInput.value.trim().toLowerCase();
  const scope = scopeFilter.value;
  const status = statusFilter.value;
  const level = levelFilter.value;

  const filtered = allConcursos.filter((item) => {
    if (scope !== "ALL" && item.escopo !== scope) return false;
    if (status !== "ALL" && item.status_inscricao !== status) return false;
    if (level !== "ALL") {
      const esc = (item.escolaridade || "").toLowerCase();
      if (level === "Superior" && !esc.includes("superior")) return false;
      if (level === "Técnico" && !esc.includes("técnico") && !esc.includes("médio")) return false;
    }

    if (query) {
      const haystack = [
        item.orgao,
        item.cidade_base,
        item.uf,
        item.detalhes,
        ...(item.cargos_ti || []),
      ]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(query)) return false;
    }

    return true;
  });

  resultsInfo.textContent = `Exibindo ${filtered.length} de ${allConcursos.length} concurso(s) ordenados por prioridade (Nacionais no topo, seguidos pelos mais próximos de Toledo - PR).`;

  if (filtered.length === 0) {
    listContainer.innerHTML = `
      <div class="empty-state">
        Nenhum concurso encontrado para os filtros selecionados.
      </div>
    `;
    return;
  }

  listContainer.innerHTML = filtered
    .map((item, idx) => {
      const isNacional = item.escopo === "NACIONAL";
      const isNear = !isNacional && item.distancia_toledo_km !== null && item.distancia_toledo_km <= 200;

      const cardClass = isNacional
        ? "card card-nacional"
        : isNear
        ? "card card-pr-near"
        : "card card-pr";

      const locationBadge = isNacional
        ? `<span class="badge badge-nacional">🇧🇷 Nacional • Prova no PR / Capitais</span>`
        : `<span class="badge ${isNear ? "badge-distance-near" : "badge-distance"}">
             📍 ${escapeHtml(item.cidade_base)} - PR • <strong>${item.distancia_toledo_km} km</strong> de Toledo
           </span>`;

      const statusClass =
        item.status_inscricao === "Aberta" ? "badge-status-open" : "badge-status-soon";
      const statusDot = item.status_inscricao === "Aberta" ? "🟢" : "🟡";

      const cargosHtml = (item.cargos_ti || [])
        .map((c) => `<span class="cargo-pill">${escapeHtml(c)}</span>`)
        .join("");

      const salaryDisplay =
        item.salario_ate && item.salario_ate !== "Não informado"
          ? `Até R$ ${escapeHtml(item.salario_ate)}`
          : "Salário no edital";

      return `
        <article class="${cardClass}">
          <div class="card-top">
            <div class="badges-row">
              <span class="badge badge-rank">#${idx + 1}</span>
              ${locationBadge}
              <span class="badge ${statusClass}">
                ${statusDot} ${escapeHtml(item.status_inscricao)} (${escapeHtml(item.inscricoes_ate)})
              </span>
            </div>
            <span class="salary-tag">${salaryDisplay}</span>
          </div>

          <div class="card-title-row">
            <a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer" class="card-title">
              ${escapeHtml(item.orgao)}
            </a>
          </div>

          <div class="card-details">
            ${escapeHtml(item.detalhes)}
          </div>

          <div class="cargos-box">
            <span class="cargos-label">Cargos de TI Identificados (${(item.cargos_ti || []).length})</span>
            <div class="cargos-pills">
              ${cargosHtml}
            </div>
          </div>

          <div class="card-footer">
            <span>Escolaridade: <strong>${escapeHtml(item.escolaridade || "Consultar edital")}</strong></span>
            <a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer" class="btn-link">
              Ver notícia e edital no PCI ↗
            </a>
          </div>
        </article>
      `;
    })
    .join("");
}

async function init() {
  try {
    const res = await fetch("./concursos.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allConcursos = data.concursos || [];
    updateStats(data);
    renderList();
  } catch (err) {
    listContainer.innerHTML = `
      <div class="empty-state">
        Não foi possível carregar <code>concursos.json</code> (${escapeHtml(err.message)}).<br/>
        Execute <code>uv run python backend/main.py</code> para gerar os dados e sirva a pasta <code>frontend/</code>.
      </div>
    `;
  }
}

[searchInput, scopeFilter, statusFilter, levelFilter].forEach((el) => {
  el.addEventListener("input", renderList);
  el.addEventListener("change", renderList);
});

init();
