# Web Scraping PCI Concursos — Vagas de TI (PR & Nacionais)

Rastreador automatizado de concursos públicos com vagas de **Tecnologia da Informação (Nível Superior e Técnico/Médio)** com inscrições abertas ou abrindo em breve, focado em provas que podem ser realizadas no **Paraná** e ordenado pela menor distância até **Toledo - PR**.

## Estrutura do Projeto

```text
├── backend/
│   ├── main.py          # Scraper, filtros de TI/PR/Nacional e cálculo de distância até Toledo-PR
│   └── pr_cities.py     # Coordenadas oficiais (IBGE) dos 399 municípios do Paraná
├── frontend/
│   ├── index.html       # Dashboard web estático
│   ├── style.css        # Estilização responsiva
│   ├── app.js           # Filtros interativos (abrangência, status, escolaridade, busca)
│   └── concursos.json   # Dados gerados pelo backend/main.py
└── .github/
    └── workflows/
        └── scraper.yml  # GitHub Actions (cron diário + manual) que atualiza frontend/concursos.json
```

## Como Executar Localmente

1. **Executar o scraper para gerar/atualizar os dados (`frontend/concursos.json`)**:
   ```bash
   uv run python backend/main.py
   ```

2. **Visualizar o frontend**:
   Sirva a pasta `frontend/` com qualquer servidor HTTP estático:
   ```bash
   uv run python -m http.server 8000 --directory frontend
   ```
   Em seguida, acesse `http://localhost:8000` no navegador.
